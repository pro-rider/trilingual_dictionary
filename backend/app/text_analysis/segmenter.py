"""Tokenization: split arbitrary text into small meaning units.

Handles Latin words, punctuation, numbers, and — the hard part — Chinese.
Chinese segmentation uses **jieba** (a real dictionary-driven segmenter), so
今天天气很好 resolves as 今天 / 天气 / 很好 instead of one character at a time.
Segments are then re-merged where the curated phrase DB knows a longer unit
(成语 like 一见钟情, compounds like 水果). If jieba is unavailable the module
falls back to greedy longest-match against the curated list + offline dataset,
which still keeps 水果 as one compound rather than 水 + 果.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from app.services.dataset import load_entries
from app.text_analysis.phrases import CJK_WORD_SURFACES

try:  # optional dependency — degrade to greedy matching when absent
    import jieba

    jieba.setLogLevel(logging.WARNING)
    _JIEBA_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without jieba
    jieba = None
    _JIEBA_AVAILABLE = False

_SCRIPT_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_SCRIPT_NUM = re.compile(r"[0-9]")
_SCRIPT_SPACE = re.compile(r"\s")
_LAT_CHARS = re.compile(r"[a-zA-Z'’-]")
_MAX_CJK_WORD = 6
# jieba's corpus contains a few very-low-frequency phrase entries (e.g. the
# "今天天气" weather-title n-gram). Anything this rare that can be split into
# two genuinely common words is a mis-merge, not a word.
_MIN_PART_FREQ = 100


@dataclass
class RawToken:
    surface: str
    script: str  # "cjk" | "lat" | "num" | "punct" | "other"
    punct: bool = False


@lru_cache(maxsize=1)
def _known_cjk_surfaces() -> frozenset[str]:
    """All Chinese surfaces the segmenter can match (curated + dataset)."""
    known = set(CJK_WORD_SURFACES)
    try:
        for e in load_entries():
            zh = (e.get("word_zh") or "").strip()
            if zh:
                known.add(zh)
            for s in e.get("senses", []):
                zh_s = (s.get("word_zh") or "").strip()
                if zh_s:
                    known.add(zh_s)
    except Exception:
        pass
    return frozenset(known)


def _split_runs(text: str) -> list[tuple[str, str]]:
    """Group consecutive characters into script runs."""
    runs: list[tuple[str, str]] = []
    for ch in text:
        if _SCRIPT_CJK.match(ch):
            script = "cjk"
        elif _LAT_CHARS.match(ch):
            script = "lat"
        elif _SCRIPT_NUM.match(ch):
            script = "num"
        elif _SCRIPT_SPACE.match(ch):
            script = "space"
        else:
            script = "punct"
        if runs and runs[-1][0] == script:
            runs[-1] = (script, runs[-1][1] + ch)
        else:
            runs.append((script, ch))
    return runs


def _greedy_cjk(s: str) -> list[RawToken]:
    """Fallback: greedy longest-match over the curated surfaces."""
    known = _known_cjk_surfaces()
    out: list[RawToken] = []
    i = 0
    n = len(s)
    while i < n:
        matched: str | None = None
        upper = min(_MAX_CJK_WORD, n - i)
        for length in range(upper, 1, -1):
            cand = s[i:i + length]
            if cand in known:
                matched = cand
                break
        if matched is not None:
            out.append(RawToken(matched, "cjk"))
            i += len(matched)
        else:
            out.append(RawToken(s[i], "cjk"))
            i += 1
    return out


def _merge_known(words: list[str]) -> list[RawToken]:
    """Re-merge jieba output where the curated DB knows a longer unit.

    jieba is a general-purpose segmenter; 成语 and some compounds are better
    treated as one unit (they carry a figurative meaning of their own).
    """
    known = _known_cjk_surfaces()
    out: list[RawToken] = []
    i = 0
    n = len(words)
    while i < n:
        consumed = 1
        merged: str | None = None
        upper = min(_MAX_CJK_WORD, n - i)
        # Never exceed the character budget for a single merged unit.
        total = 0
        for k in range(1, upper + 1):
            total += len(words[i + k - 1])
            if total > _MAX_CJK_WORD:
                break
            cand = "".join(words[i:i + k])
            if k >= 2 and cand in known:
                merged, consumed = cand, k
        if merged is not None:
            out.append(RawToken(merged, "cjk"))
            i += consumed
        else:
            out.append(RawToken(words[i], "cjk"))
            i += 1
    return out


def _split_low_freq(word: str) -> list[str]:
    """Split a rare jieba n-gram merge back into its common constituent words."""
    if not _JIEBA_AVAILABLE or len(word) < 3:
        return [word]
    try:
        jieba.dt.check_initialized()
        freq = jieba.dt.FREQ
    except Exception:
        return [word]
    if freq.get(word, 0) >= _MIN_PART_FREQ:
        return [word]
    best: tuple[int, str, str] | None = None
    for k in range(1, len(word)):
        left, right = word[:k], word[k:]
        fl, fr = freq.get(left, 0), freq.get(right, 0)
        if fl >= _MIN_PART_FREQ and fr >= _MIN_PART_FREQ:
            score = min(fl, fr)
            if best is None or score > best[0]:
                best = (score, left, right)
    if best is None:
        return [word]
    return _split_low_freq(best[1]) + _split_low_freq(best[2])


def _segment_cjk(s: str) -> list[RawToken]:
    if _JIEBA_AVAILABLE:
        pieces = [
            piece
            for w in jieba.cut(s, HMM=False)
            for piece in _split_low_freq(w)
        ]
        words = [w for w in pieces if w.strip()]
        if words:
            return _merge_known(words)
    return _greedy_cjk(s)


def tokenize(text: str) -> list[RawToken]:
    """Tokenize any text into words, compounds, idioms-to-be and punctuation."""
    tokens: list[RawToken] = []
    for script, run in _split_runs(text):
        if script == "space":
            continue
        if script == "cjk":
            tokens.extend(_segment_cjk(run))
        elif script in ("lat", "num"):
            for word in run.split():
                tokens.append(RawToken(word, "lat" if script == "lat" else "num"))
        else:  # punct / other
            tokens.append(RawToken(run, script, punct=(script == "punct")))
    return tokens


def meaningful(tokens: list[RawToken]) -> list[RawToken]:
    """Non-punctuation, non-whitespace tokens worth translating."""
    return [t for t in tokens if not t.punct and t.surface.strip()]
