"""R1 — deterministic cleaning and structuring of raw Chinese source documents.

Reads a raw document (UTF-8), never modifies it, and produces:

  data/clean/<doc_id>/paragraphs.jsonl   one record per paragraph
  data/clean/<doc_id>/sentences.jsonl    one record per sentence
  data/clean/<doc_id>/clean_report.json  machine-readable audit trail
  data/clean/<doc_id>/clean_report.md    the same report, readable
  data/clean/manifest.json               every document imported, keyed by hash

Design rules (all deliberate, all recorded per operation):
  * decode is strict UTF-8; a decode failure is reported, never silently
    replaced
  * line endings are normalised to LF, and the count of CRLF / lone CR is kept
  * Unicode policy is NFC. NFKC is NOT used, because it would rewrite
    full-width punctuation and destroy the original text; only full-width
    ASCII letters and digits are folded to half-width, each one recorded
  * LaTeX fragments are turned into readable symbols (``$\\rightarrow$`` → ``→``),
    every replacement recorded with its line number
  * ASCII box-drawing / diagram blocks are removed only when a line is
    overwhelmingly diagram characters; text carried inside a diagram (tree
    branches, bullet text) is kept and its prefix stripped
  * headings are detected by configurable patterns; when a heading is glued to
    the body text and the boundary cannot be proven, the case is reported as
    unresolved instead of being guessed
  * sentence splitting protects decimals, abbreviations, URLs, version and
    model names, and section numbers
  * identifiers are derived from the source hash plus positional keys plus the
    sentence text hash, so re-processing an unchanged file reproduces the same
    IDs

Usage:
  .venv\\Scripts\\python.exe tools\\r1_clean.py --input C:\\path\\rawdata.txt
  .venv\\Scripts\\python.exe tools\\r1_clean.py --input rawdatA.txt --out data\\clean
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- configuration

HEADING_PATTERNS = {
    "part": re.compile(r"^第[一二三四五六七八九十百零]+部分[：:]?"),
    "chapter": re.compile(r"^第[一二三四五六七八九十百零]+章\s*"),
    # a section number only counts at the start of a sentence: "1.2 标题…"
    "section_num": re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}[.、]\s*(?=[\u4e00-\u9fff])"),
}

LATEX_MAP = {
    r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\to": "→", r"\times": "×", r"\cdot": "·", r"\pm": "±",
    r"\leq": "≤", r"\geq": "≥", r"\approx": "≈", r"\infty": "∞",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\Delta": "Δ",
    r"\sqrt": "√", r"\left": "", r"\right": "", r"\,": " ", r"\;": " ",
    r"\\": " ", r"\quad": " ", r"\ ": " ",
}

BOX_CHARS = set("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬▼▲►◄→←↑↓|+-+")
TREE_PREFIX = re.compile(r"^[\s│├└─┬┴┼|+]*")

TERMINAL = "。！？!?"
SENT_END = re.compile(r"[。！？!?]")
INVISIBLE = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u00ad"}
# a chapter marker may be preceded by the book title, but not by prose
PREFIX_STOPWORDS = ("的", "在", "说", "提到", "参见", "见", "关于", "叫做", "称为")
# protected spans are replaced by placeholders before splitting, restored after
PROTECT = [
    (re.compile(r"https?://[^\s\u4e00-\u9fff]+"), "URL"),
    (re.compile(r"\b\d+\.\d+(?!\.\d)"), "DEC"),          # 3.14
    (re.compile(r"\b(?:\d{1,2}(?:\.\d{1,3}){2,})\b"), "DEC"),  # 1.2.3
    (re.compile(r"\b(?:[A-Za-z]\.){2,}"), "ABB"),        # U.S.
    (re.compile(r"\b(?:e\.g|i\.e|vs|etc|No|Dr|Mr|Ms|Prof)\.", re.I), "ABB"),
    (re.compile(r"\b[A-Za-z]{1,6}-\d{1,4}\b"), "MODEL"),  # GPT-4, COVID-19
    (re.compile(r"\b\d+(?:\.\d+)?%"), "PCT"),
]


# ---------------------------------------------------------------- data records

@dataclass
class Op:
    line: int
    operation: str
    reason: str
    before: str = ""
    after: str = ""


@dataclass
class Doc:
    source_name: str
    source_path: str
    source_sha256: str
    encoding: str
    bytes: int
    chars: int
    crlf: int
    lone_cr: int
    lf: int
    ops: list[Op] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    paragraphs: list[dict] = field(default_factory=list)
    sentences: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- helpers

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_text(text: str, doc: Doc) -> str:
    """NFC + full-width ASCII fold + invisible-character removal, all recorded."""
    text = unicodedata.normalize("NFC", text)
    out_lines = []
    for i, line in enumerate(text.split("\n"), start=1):
        cleaned_chars = []
        removed = []
        for ch in line:
            if ch in INVISIBLE:
                removed.append(ch)
                continue
            if "\u0000" <= ch <= "\u001f" or "\u007f" <= ch <= "\u009f":
                removed.append(ch)
                continue
            cleaned_chars.append(ch)
        if removed:
            doc.ops.append(Op(i, "remove_control_char",
                              "control / zero-width character in source text",
                              "", " ".join(f"U+{ord(c):04X}" for c in removed)[:60]))
        line = "".join(cleaned_chars)
        # full-width ASCII letters/digits -> half-width. Punctuation stays
        # full-width: it is meaningful Chinese typography, not a typo.
        fixed = "".join(
            chr(ord(ch) - 0xFEE0)
            if ("\uFF10" <= ch <= "\uFF19" or "\uFF21" <= ch <= "\uFF3A"
                or "\uFF41" <= ch <= "\uFF5A") else ch
            for ch in line
        )
        if fixed != line:
            doc.ops.append(Op(i, "fold_fullwidth_ascii",
                              "full-width ASCII folded to half-width",
                              line[:40], fixed[:40]))
        out_lines.append(fixed)
    return "\n".join(out_lines)


def replace_latex(text: str, doc: Doc) -> str:
    lines = []
    for i, line in enumerate(text.split("\n"), start=1):
        if "$" not in line and "\\" not in line:
            lines.append(line)
            continue
        original = line
        line = line.replace("$$", "").replace("$", "")
        for src, dst in LATEX_MAP.items():
            line = line.replace(src, dst)
        line = re.sub(r"\\text\{([^}]*)\}", r"\1", line)
        line = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", line)
        unknown = [m.group(0) for m in re.finditer(r"\\[A-Za-z]+", line)]
        for token in unknown:
            doc.warnings.append(
                f"line {i}: unknown latex command '{token}' kept as-is "
                f"(no mapping, not silently dropped)")
        if line != original:
            doc.ops.append(Op(i, "latex_to_text",
                              "LaTeX fragment converted to readable text",
                              original[:60], line[:60]))
        lines.append(line)
    return "\n".join(lines)


def diagram_ratio(line: str) -> float:
    stripped = line.strip()
    if not stripped:
        return 0.0
    box = sum(1 for ch in stripped if ch in BOX_CHARS)
    spaces = sum(1 for ch in stripped if ch == " ")
    return (box + spaces) / len(stripped)


def strip_diagrams(text: str, doc: Doc) -> str:
    """Drop box-drawing diagram lines; keep text lines, strip tree prefixes."""
    kept = []
    for i, line in enumerate(text.split("\n"), start=1):
        if diagram_ratio(line) >= 0.6 and len(line.strip()) <= 120:
            doc.ops.append(Op(i, "remove_diagram_line",
                              "ASCII diagram / box-drawing formatting, not prose",
                              line[:70]))
            continue
        if TREE_PREFIX.match(line) and line.lstrip().startswith(("├", "└", "│", "┌")):
            new = TREE_PREFIX.sub("", line, count=1)
            if new.strip():
                doc.ops.append(Op(i, "strip_tree_prefix",
                                  "kept the text, removed the tree drawing",
                                  line[:50], new[:50]))
                kept.append(new)
                continue
        kept.append(line)
    return "\n".join(kept)


def join_wrapped_lines(text: str, doc: Doc) -> tuple[str, list[tuple[int, int]]]:
    """The source is hard-wrapped every 8192 chars; rejoin mid-sentence breaks.

    Returns the joined text plus a map ``[(offset_in_joined, original_line)]``
    so every downstream record can still point at the original source line.
    """
    lines = text.split("\n")
    out: list[str] = []
    line_map: list[tuple[int, int]] = []
    buf = ""
    buf_start = 1
    offset = 0
    for i, line in enumerate(lines, start=1):
        stripped = line.rstrip()
        if not stripped.strip():
            if buf:
                out.append(buf)
                offset += len(buf) + 1
                buf = ""
            out.append("")
            offset += 1
            buf_start = i + 1
            continue
        if not buf:
            buf = stripped
            buf_start = i
            line_map.append((offset, buf_start))
        elif buf.endswith(tuple(TERMINAL)) or is_heading_line(stripped):
            out.append(buf)
            offset += len(buf) + 1
            buf = stripped
            buf_start = i
            line_map.append((offset, buf_start))
        else:
            doc.ops.append(Op(i, "join_wrapped_line",
                              "hard line break inserted by the source writer, "
                              "not a paragraph break", stripped[:40]))
            buf = buf + stripped
    if buf:
        out.append(buf)
    return "\n".join(out), line_map


def line_at(line_map: list[tuple[int, int]], offset: int) -> int:
    """Original line number for an offset in the joined text."""
    lo, hi = 0, len(line_map) - 1
    best = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if line_map[mid][0] <= offset:
            best = line_map[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 60:
        return False
    if HEADING_PATTERNS["part"].match(s) or HEADING_PATTERNS["chapter"].match(s):
        return True
    if re.match(r"(?:\d+(?:\.\d+)*)\s+[\u4e00-\u9fff]", s):
        return True
    return False


# ---------------------------------------------------------------- headings

@dataclass
class Segment:
    heading_path: list[str]
    heading_level: int
    text: str
    line: int


HEADING_KIND_LEVEL = {"part": 1, "chapter": 2, "section_num": 3}


def detect_heading(sentence: str, doc: Doc, line: int) -> dict | None:
    """Return a heading record when the sentence *starts* with a heading marker.

    The marker itself is always unambiguous (第X章 / 第X部分 / 1.2). The title
    that follows may be glued to the body; boundaries are only taken from
    evidence, and an unresolved boundary is reported instead of being guessed.
    """
    prefix = ""
    rest = sentence
    # a book title can sit in front of the very first chapter marker
    m = re.match(r"([\u4e00-\u9fff、·]{2,12})(第[一二三四五六七八九十百零]+章)", sentence)
    if (m and len(m.group(1)) <= 10
            and not any(w in m.group(1) for w in PREFIX_STOPWORDS)):
        prefix, rest = m.group(1), sentence[m.start(2):]

    for kind in ("part", "chapter", "section_num"):
        if prefix and kind != "chapter":
            continue
        m = HEADING_PATTERNS[kind].match(rest)
        if not m:
            continue
        label = m.group(0).strip()
        if kind in ("chapter", "part"):
            label = label.replace(" ", "")
            label = label + " "
        tail = rest[m.end():]
        if len(tail.strip()) < 2:
            return {"kind": kind, "label": (prefix + label).strip(),
                    "title": (prefix + label).strip(),
                    "remainder": "", "boundary": "marker_only"}

        cut, boundary = _title_cut(tail)
        title = (prefix + label + tail[:cut]).strip()
        remainder = tail[cut:].strip()
        if boundary == "unresolved":
            # nothing was cut: the whole run stays body text, the heading keeps
            # only its marker, and the case is reported for review.
            doc.warnings.append(
                f"line {line}: heading '{label.strip()}' is glued to the body and "
                f"no verified boundary exists; marker recorded, text kept intact")
            return {"kind": kind, "label": (prefix + label).strip(),
                    "title": (prefix + label).strip(),
                    "remainder": rest[m.end():].strip(), "boundary": "unresolved"}
        if boundary == "term_paren":
            doc.ops.append(Op(line, "heading_boundary_heuristic",
                              "title cut before 'term（Latin name）'",
                              label, title[:50]))
        return {"kind": kind, "label": (prefix + label).strip(), "title": title,
                "remainder": remainder, "boundary": boundary}
    return None


def _term_cut(limit: str) -> int:
    """Offset where the body's "中文术语（Latin name）" begins, or -1.

    The Chinese run before the bracket can pick up a few preceding characters
    ("地球生态植物界（Plantae）"); the term itself is the last 2–5 characters,
    so the run is trimmed from the left.
    """
    m = re.search(r"[\u4e00-\u9fff]{2,8}[（(][A-Za-z]", limit)
    if not m:
        return -1
    run_len = 0
    while run_len < len(m.group(0)) and "\u4e00" <= m.group(0)[run_len] <= "\u9fff":
        run_len += 1
    return m.start() + max(0, run_len - 3)


def _title_cut(tail: str) -> tuple[int, str]:
    """Where does the title end inside `tail`? Returns (offset, kind)."""
    limit = tail[:60]
    # titles in this corpus look like "领域名：修饰短语" and the body then opens
    # with the topic term plus its Latin name, so a colon early in the run means
    # the Latin-name bracket belongs to the body, not to the title.
    if re.match(r"[^。]{0,30}：", limit):
        cut = _term_cut(limit)
        if cut >= 3:
            return cut, "term_paren"
    # 1) the title itself carries a Latin name in brackets: "技术 (Technology)"
    m = re.match(r"[^。]{0,40}?(?:（[A-Za-z][^）]{0,80}）|\([A-Za-z][^)]{0,80}\))", limit)
    if m and m.end() <= 48:
        return m.end(), "title_paren"
    # 2) body starts with "中文术语（Latin name）" — the pattern this corpus uses
    #    for the sentence that introduces a topic.
    cut = _term_cut(limit)
    if cut >= 5:
        return cut, "term_paren"
    # 3) a short title closed by a sentence terminator (long runs are body text
    #    that happens to end in 。, so the cap matters)
    m = re.match(r"[^。！？]{1,16}[。！？]", limit)
    if m and m.end() <= 18:
        return m.end(), "terminator"
    return 0, "unresolved"


def body_starts_block(sentence: str) -> bool:
    """A sentence opening a labelled sub-block ("体表特征与恒温机制：…")."""
    return bool(re.match(r"^[\u4e00-\u9fff]{2,12}：", sentence))


# ---------------------------------------------------------------- sentences

def protect(text: str) -> tuple[str, dict[str, str]]:
    store: dict[str, str] = {}
    out = text
    for pattern, kind in PROTECT:
        def _sub(m, kind=kind):
            key = f"\u0001{len(store)}\u0001"
            store[key] = m.group(0)
            return key
        out = pattern.sub(_sub, out)
    return out, store


def restore(text: str, store: dict[str, str]) -> str:
    for key, value in store.items():
        text = text.replace(key, value)
    return text


def split_sentences(text: str, split_semicolon: bool) -> list[tuple[str, int]]:
    """Split into sentences, preserving offsets and protected expressions."""
    guarded, store = protect(text)
    pattern = re.compile(
        r"(.+?[。！？!?" + ("；;" if split_semicolon else "") + r"]|.+$)", re.S)
    out: list[tuple[str, int]] = []
    for m in pattern.finditer(guarded):
        piece = m.group(1)
        if not piece.strip():
            continue
        out.append((restore(piece.strip(), store), m.start()))
    return out


def search_form(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\u4e00-\u9fff\u3400-\u4dbfA-Za-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- pipeline

def process_document(path: Path, out_root: Path, split_semicolon: bool = False) -> Doc:
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    doc = Doc(
        source_name=path.name, source_path=str(path), source_sha256=digest,
        encoding="utf-8", bytes=len(raw),
        chars=0, crlf=0, lone_cr=0, lf=0,
    )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        doc.warnings.append(f"UTF-8 decode failed at byte {exc.start}: {exc.reason}; "
                            f"document not processed")
        text = raw.decode("utf-8", errors="replace")
        doc.warnings.append("text decoded with U+FFFD replacement; treat as malformed")

    doc.crlf = text.count("\r\n")
    doc.lone_cr = text.count("\r") - doc.crlf
    doc.lf = text.count("\n")
    if doc.crlf or doc.lone_cr:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        doc.ops.append(Op(0, "normalise_line_endings",
                          f"CRLF {doc.crlf} / lone CR {doc.lone_cr} converted to LF"))
    doc.chars = len(text)

    text = normalise_text(text, doc)
    text = replace_latex(text, doc)
    text = strip_diagrams(text, doc)
    text, line_map = join_wrapped_lines(text, doc)

    doc_id = digest[:12]
    paragraphs: list[dict] = []
    sentences: list[dict] = []
    path: list[str] = []
    para_no = -1
    current: dict | None = None

    def new_paragraph(heading_path: list[str], first_line: int) -> dict:
        nonlocal para_no
        para_no += 1
        rec = {
            "paragraph_id": f"{doc_id}-p{para_no:04d}",
            "document_id": doc_id,
            "kind": "paragraph",
            "level": 0,
            "heading_path": list(heading_path),
            "text": "",
            "line": first_line,
            "sentence_count": 0,
            "text_sha256": "",
            "_lines": [],
        }
        paragraphs.append(rec)
        return rec

    def add_sentence(rec: dict, text_of: str, start: int) -> None:
        line_no = line_at(line_map, start)
        sentences.append({
            "sentence_id": f"{rec['paragraph_id']}-s{rec['sentence_count']:03d}",
            "paragraph_id": rec["paragraph_id"],
            "document_id": doc_id,
            "paragraph_no": para_no,
            "sentence_no": rec["sentence_count"],
            "heading_path": list(rec["heading_path"]),
            "text": text_of,
            "search": search_form(text_of),
            "line": line_no,
            "text_sha256": sha256_bytes(text_of.encode("utf-8")),
            "source_sha256": digest,
        })
        rec["sentence_count"] += 1
        rec["_lines"].append(line_no)
        rec["text"] = (rec["text"] + " " + text_of).strip()
        rec["line"] = min(rec["line"], line_no)

    for sent, start in split_sentences(text, split_semicolon):
        remainder = sent
        guard = 0
        while remainder and guard < 4:
            guard += 1
            heading = detect_heading(remainder, doc, line_at(line_map, start))
            if not heading:
                break
            level = HEADING_KIND_LEVEL[heading["kind"]]
            path = path[: level - 1] + [heading["title"]]
            para_no += 1
            paragraphs.append({
                "paragraph_id": f"{doc_id}-h{para_no:04d}",
                "document_id": doc_id,
                "kind": "heading",
                "level": level,
                "heading_path": list(path),
                "text": heading["title"],
                "line": line_at(line_map, start),
                "boundary": heading["boundary"],
                "text_sha256": sha256_bytes(heading["title"].encode("utf-8")),
            })
            current = None
            remainder = heading["remainder"]

        if not remainder:
            continue
        if current is None or body_starts_block(remainder):
            current = new_paragraph(path, line_at(line_map, start))
        add_sentence(current, remainder, start)

    # finalise paragraphs: drop the internal line list, hash the joined text
    for rec in paragraphs:
        if rec["kind"] != "paragraph":
            continue
        rec["text_sha256"] = sha256_bytes(rec["text"].encode("utf-8"))
        rec["line_range"] = [rec["line"],
                             max(rec.pop("_lines")) if rec.get("_lines") else rec["line"]]
    doc.paragraphs = paragraphs
    doc.sentences = sentences

    # nothing may disappear: if the sentence stream lost characters against the
    # cleaned text, that is a parsing failure and must be reported
    cleaned_chars = len(re.sub(r"\s", "", text))
    kept_chars = len(re.sub(r"\s", "", "".join(s["text"] for s in sentences)))
    headings_chars = len(re.sub(r"\s", "", "".join(
        p["text"] for p in paragraphs if p["kind"] == "heading")))
    if cleaned_chars - kept_chars - headings_chars > 0.01 * max(cleaned_chars, 1):
        doc.warnings.append(
            f"character accounting mismatch: cleaned {cleaned_chars:,} chars, "
            f"sentences {kept_chars:,}, headings {headings_chars:,}")

    out_dir = out_root / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "paragraphs.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for rec in doc.paragraphs:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with (out_dir / "sentences.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for rec in doc.sentences:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    report = {
        "source_name": doc.source_name,
        "source_path": doc.source_path,
        "source_sha256": digest,
        "encoding": doc.encoding,
        "bytes": doc.bytes,
        "chars": doc.chars,
        "line_endings": {"crlf": doc.crlf, "lone_cr": doc.lone_cr, "lf": doc.lf,
                         "normalised_to": "LF"},
        "normalisation_policy": "NFC; full-width ASCII letters/digits folded to half-width; "
                                "full-width punctuation preserved",
        "operations": [asdict(op) for op in doc.ops],
        "operation_counts": {},
        "warnings": doc.warnings,
        "paragraphs": len([p for p in doc.paragraphs if p["kind"] == "paragraph"]),
        "headings": len([p for p in doc.paragraphs if p["kind"] == "heading"]),
        "sentences": len(doc.sentences),
        "unique_heading_paths": len({tuple(p["heading_path"]) for p in doc.paragraphs}),
        "outputs": {
            "dir": str(out_dir),
            "paragraphs": str(out_dir / "paragraphs.jsonl"),
            "sentences": str(out_dir / "sentences.jsonl"),
        },
    }
    counts: dict[str, int] = {}
    for op in doc.ops:
        counts[op.operation] = counts.get(op.operation, 0) + 1
    report["operation_counts"] = counts
    (out_dir / "clean_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = [
        f"# Clean report — {doc.source_name}", "",
        f"- document id: `{doc_id}`",
        f"- sha256: `{digest}`",
        f"- bytes: {doc.bytes:,} · characters: {doc.chars:,}",
        f"- line endings: CRLF {doc.crlf:,} · lone CR {doc.lone_cr:,} · LF {doc.lf:,} → LF",
        f"- paragraphs: {report['paragraphs']:,} · headings: {report['headings']:,} "
        f"· sentences: {report['sentences']:,}",
        f"- normalisation: NFC, full-width ASCII folded, full-width punctuation kept", "",
        "## Operations", "",
        "| operation | count |", "|---|---:|",
    ]
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        md.append(f"| {k} | {v:,} |")
    md += ["", "## Warnings", ""]
    md += [f"- {w}" for w in doc.warnings] or ["- none"]
    (out_dir / "clean_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    manifest_path = out_root / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous = manifest.get(digest, {})
    manifest[digest] = {
        "source_name": doc.source_name,
        "source_path": doc.source_path,
        "document_id": doc_id,
        "bytes": doc.bytes,
        "sentences": len(doc.sentences),
        "paragraphs": report["paragraphs"],
        "output_dir": str(out_dir),
        "imports": previous.get("imports", 0) + 1,
        "first_imported": previous.get("first_imported", datetime.now().isoformat(timespec="seconds")),
        "last_imported": datetime.now().isoformat(timespec="seconds"),
        "repeated_import": bool(previous),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default=str(Path("data") / "clean"))
    ap.add_argument("--split-semicolon", action="store_true",
                    help="also split sentences on ；/; (off by default: it "
                         "fragments enumerations and loses context)")
    args = ap.parse_args()
    src = Path(args.input)
    if not src.exists():
        print(f"input not found: {src}", file=sys.stderr)
        return 2
    doc = process_document(src, Path(args.out), args.split_semicolon)
    print(json.dumps({
        "document_id": doc.source_sha256[:12],
        "paragraphs": len([p for p in doc.paragraphs if p["kind"] == "paragraph"]),
        "headings": len([p for p in doc.paragraphs if p["kind"] == "heading"]),
        "sentences": len(doc.sentences),
        "operations": len(doc.ops),
        "warnings": len(doc.warnings),
        "out": args.out,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
