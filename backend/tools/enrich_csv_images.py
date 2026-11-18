"""Fill `image_link` (and its provenance columns) in a CSV — review material only.

What this is, and what it is deliberately not
---------------------------------------------
A workbook helper: read a sheet, build one query per row from the English column,
ask a licence-aware provider for a single picture, and write a **new** CSV with

    image_link, image_licence, image_creator, image_source_page, image_provider

It is *not* the path that puts pictures into the app. ``build_image_index.py``
owns that and is stricter on purpose: identity is the Wikidata concept, the
licence gate only admits CC0 / CC BY / public domain, and a thumbnail over
15,000 bytes is rejected. Everything written here is **candidate material for
review**: never ``asset_status='approved'``, never loaded into
``concept_images``. ``audit_images.py`` exists to catch rows that skipped the
gate, so do not let these rows skip it.

Providers (verified against the providers' own documentation)
-------------------------------------------------------------
``commons`` (default)
    Wikimedia Commons MediaWiki action API:
    ``action=query&generator=search&gsrsearch=...&gsrnamespace=6`` (File
    namespace) ``&prop=imageinfo&iiprop=url|size|extmetadata|mime&iiurlwidth=320``.
    Licence comes from ``extmetadata`` (``LicenseShortName`` / ``License``),
    creator from ``Artist``, source page from ``descriptionurl``.
    Wikimedia's User-Agent policy requires a descriptive agent with a contact,
    so ``--contact`` (or ``IMAGE_LOOKUP_CONTACT``) is put in the header; without
    it the tool warns instead of silently pretending to comply.

``openverse``
    ``https://api.openverse.org/v1/images/?q=...&license=cc0,pdm,by&page_size=...``
    (licence codes per ``api/constants/licenses.py``: ``cc0``, ``pdm``, ``by``).
    Returns ``url``, ``thumbnail``, ``license``, ``creator``,
    ``foreign_landing_url``.

``offline``
    Deterministic mapping, for tests. There is no scraping provider and no
    Google Custom Search: CSE is closed to new customers and retires on
    2027-01-01, and HTML scraping breaks the providers' terms.

Every candidate is re-checked against ``ALLOWED_LICENCES`` and dropped when it
falls outside it — the provider's filter is a convenience, this gate is the
decision.

Why the output is review-only
-----------------------------
A bare polysemous word resolves to whichever sense the search engine ranked
first: ``bank`` may come back as a river bank, a financial institution, or a
building. The first Commons/Openverse hit for such a word is frequently the
wrong sense, and only a person looking at the picture can tell. ``--context-column``
(the gloss column) narrows it, it does not settle it.

Behaviour worth knowing
-----------------------
  * rows are normalised right after load (short rows, long rows with extra
    fields, ``None`` cells), so a malformed file fails **before** any query is
    spent;
  * ``--limit N`` / ``--start N`` process a window but still write every row,
    with the untouched rows' output columns blank (never stale);
  * ``--max-queries`` is a hard budget of network calls for the run;
  * the cache keys on provider + normalised query + template version, stores
    misses as ``null`` (``--retry-misses`` re-queries them), and is written
    atomically every N successes and on exit;
  * provider errors are classified: 429/5xx/timeouts/resets are retried with
    backoff (``Retry-After`` honoured), while 400/401/403 and quota/auth
    messages stop the run — partial output is written and the exit code is 3.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import math
import os
import re
import socket
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

IMAGE_COLUMN = "image_link"
IMAGE_LICENCE_COLUMN = "image_licence"
IMAGE_CREATOR_COLUMN = "image_creator"
IMAGE_SOURCE_PAGE_COLUMN = "image_source_page"
IMAGE_PROVIDER_COLUMN = "image_provider"

OUTPUT_COLUMNS = (
    IMAGE_COLUMN,
    IMAGE_LICENCE_COLUMN,
    IMAGE_CREATOR_COLUMN,
    IMAGE_SOURCE_PAGE_COLUMN,
    IMAGE_PROVIDER_COLUMN,
)

# The single licence authority for this tool. tools/build_image_index.py holds
# the shipped gate (ALLOWED_LICENCE regex); this set is the same policy in
# matchable form, and tests/test_enrich_csv_images.py asserts the two agree.
ALLOWED_LICENCES = frozenset({"cc0", "cc by", "cc by-sa", "public domain"})

# Refuse anything that adds restrictions on top of attribution.
FORBIDDEN_LICENCE = re.compile(r"\b(nc|nd|noncommercial|no.?deriv)\b", re.IGNORECASE)

COMMONS_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_ENDPOINT = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENCES = "cc0,pdm,by"

DEFAULT_CACHE = Path(__file__).resolve().parents[1] / ".cache" / "image_link_cache.json"
THUMB_WIDTH = 320
RESULTS_PER_QUERY = 5
PERSIST_EVERY = 10

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
TAGS = re.compile(r"<[^>]+>")
PINYIN_HEADER = re.compile(r"pinyin|拼音|romaji|romaniz", re.IGNORECASE)

_MISSING = object()


# ---------------------------------------------------------------------------
# Candidate + licence gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One picture, with the provenance a reviewer needs to judge it."""

    url: str
    thumb_url: str = ""
    licence: str = ""
    creator: str = ""
    source_page: str = ""
    provider: str = ""

    def as_cache(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_cache(cls, payload: Mapping[str, str]) -> "Candidate":
        return cls(
            url=payload.get("url", ""),
            thumb_url=payload.get("thumb_url", ""),
            licence=payload.get("licence", ""),
            creator=payload.get("creator", ""),
            source_page=payload.get("source_page", ""),
            provider=payload.get("provider", ""),
        )


def normalise_licence(raw: str | None) -> str:
    """Map a provider's licence string onto one of ALLOWED_LICENCES, or ''.

    The mapping is explicit because "CC BY-SA 4.0", "by-sa" and "cc-by-sa"
    are the same licence, and a silent mismatch between the providers'
    vocabularies is exactly what lets a non-commercial image through.
    """
    if not raw:
        return ""
    text = re.sub(r"\s+", " ", str(raw)).strip().lower()
    if not text:
        return ""
    if FORBIDDEN_LICENCE.search(text):
        return ""
    if text.startswith("cc0") or text.startswith("cc 0") or text == "cc-zero":
        return "cc0"
    if text in {"pd", "pdm"} or "public domain" in text or "publicdomain" in text:
        return "public domain"
    if re.match(r"cc[- ]?by[- ]?sa", text) or text in {"by-sa", "cc by sa"}:
        return "cc by-sa"
    if re.match(r"cc[- ]?by(\s|$|[0-9])", text) or text == "by" or text.startswith("cc-by "):
        return "cc by"
    return ""


def licence_is_allowed(licence: str) -> bool:
    return licence in ALLOWED_LICENCES


def _plain(html_or_text: str | None) -> str:
    """extmetadata arrives HTML-formatted; a workbook cell should not."""
    if not html_or_text:
        return ""
    import html as html_module

    text = TAGS.sub(" ", str(html_or_text))
    return re.sub(r"\s+", " ", html_module.unescape(text)).strip()


# Glosses that describe grammar rather than a photographable thing. Searching
# Commons for "to reach" returns a random landscape; a blank cell with a logged
# reason is the honest answer, and it costs no network call to conclude that.
UNSEARCHABLE_PREFIXES = (
    "to ", "variant of", "see ", "same as", "used in", "used as", "abbr",
    "short for", "surname", "classifier for", "erhua", "old variant",
)
UNSEARCHABLE_EXACT = frozenset({
    "thing", "person", "place", "action", "state", "quality", "way", "kind",
    "cl", "sth", "sb", "etc", "unknown", "n/a",
})
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "in", "on", "at", "for", "and", "or", "with", "by",
    "to", "from", "as", "is", "are", "be", "that", "this", "it", "its",
})


def query_is_searchable(term: str) -> tuple[bool, str]:
    """Whether a gloss can plausibly name a picture, plus the reason if not."""
    text = re.sub(r"\s+", " ", (term or "").strip().lower())
    if not text:
        return False, "empty cell"
    if text in UNSEARCHABLE_EXACT:
        return False, "metalinguistic gloss"
    for prefix in UNSEARCHABLE_PREFIXES:
        if text.startswith(prefix):
            return False, f"not a pictureable concept ({prefix.strip()})"
    return True, ""


def title_matches_query(query: str, title: str) -> bool:
    """Cheap relevance gate: one meaningful query token must appear in the title.

    Commons search ranks lexically, so the top hit for a polysemous or vague
    gloss is often unrelated ("reach" -> a mountain). Filing that as the
    dictionary image would be worse than leaving the row blank, and the gate
    costs nothing beyond string work on a response already in hand.
    """
    def tokens(text: str) -> set[str]:
        cleaned = re.sub(r"[^0-9a-z]+", " ", (text or "").casefold())
        return {token for token in cleaned.split() if len(token) >= 3 and token not in _STOPWORDS}

    query_tokens = tokens(query)
    title_tokens = tokens(title)
    if not query_tokens or not title_tokens:
        return False
    return bool(query_tokens & title_tokens)


# ---------------------------------------------------------------------------
# Transport + error classes
# ---------------------------------------------------------------------------

class Retryable(Exception):
    """429/5xx/timeouts/resets: back off and try the same row again."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class FatalProviderError(Exception):
    """Auth, quota or a bad request: the whole run must stop (exit 3)."""


class ProviderRowError(Exception):
    """This row's lookup failed; the run continues."""


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        return None


def _request_json(
    url: str, params: Mapping[str, str], headers: Mapping[str, str], timeout: float
) -> dict:
    query = urllib.parse.urlencode(params)
    full = f"{url}?{query}" if query else url
    request = urllib.request.Request(full, headers=dict(headers))

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        retry_after = _parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # pragma: no cover - body already consumed
            detail = ""
        if exc.code == 429 or 500 <= exc.code <= 599:
            raise Retryable(f"HTTP {exc.code}", retry_after=retry_after) from exc
        if exc.code in (400, 401, 403):
            raise FatalProviderError(f"HTTP {exc.code}: {detail or 'no detail'}") from exc
        raise ProviderRowError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise Retryable(f"connection: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise Retryable("timeout") from exc
    except (ConnectionResetError, http.client.HTTPException) as exc:
        raise Retryable(f"transport: {type(exc).__name__}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProviderRowError(f"malformed JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class CommonsProvider:
    """Commons File-namespace search, licence read from extmetadata."""

    def __init__(
        self,
        contact: str = "",
        thumb_width: int = THUMB_WIDTH,
        results: int = RESULTS_PER_QUERY,
        timeout: float = 20.0,
    ) -> None:
        self._contact = contact
        self._thumb_width = thumb_width
        self._results = results
        self._timeout = timeout

    def user_agent(self) -> str:
        # meta.wikimedia.org/wiki/User-Agent_policy: descriptive, with contact.
        contact = self._contact or "contact not configured"
        return (
            "TrilingualDictionaryImageCandidates/0.2 "
            f"(dictionary image review; contact: {contact}) python-urllib"
        )

    def __call__(self, query: str) -> Candidate | None:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",
            "gsrlimit": str(self._results),
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|mime",
            "iiurlwidth": str(self._thumb_width),
            "iiextmetadatafilter": "LicenseShortName|License|Artist",
        }
        headers = {"User-Agent": self.user_agent(), "Accept": "application/json"}
        payload = _request_json(COMMONS_ENDPOINT, params, headers, self._timeout)

        pages = (payload.get("query") or {}).get("pages") or {}
        entries = pages.values() if isinstance(pages, dict) else pages

        for page in entries:
            info = (page.get("imageinfo") or [{}])[0]
            mime = (info.get("mime") or "").lower()
            if mime and not mime.startswith("image/"):
                continue
            url = info.get("url") or ""
            if not url.startswith("https://"):
                continue
            if not title_matches_query(query, _plain(page.get("title"))):
                continue

            meta = info.get("extmetadata") or {}
            raw_licence = _meta(meta, "LicenseShortName") or _meta(meta, "License")
            licence = normalise_licence(raw_licence)
            if not licence_is_allowed(licence):
                continue

            return Candidate(
                url=url,
                thumb_url=info.get("thumburl") or url,
                licence=licence,
                creator=_plain(_meta(meta, "Artist")),
                source_page=info.get("descriptionurl") or "",
                provider="commons",
            )
        return None


def _meta(extmetadata: Mapping[str, object], key: str) -> str:
    entry = extmetadata.get(key)
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return ""


class OpenverseProvider:
    """Openverse images search, restricted to cc0 / pdm / by."""

    def __init__(self, results: int = RESULTS_PER_QUERY, timeout: float = 20.0) -> None:
        self._results = results
        self._timeout = timeout

    def __call__(self, query: str) -> Candidate | None:
        params = {
            "q": query,
            "license": OPENVERSE_LICENCES,
            "page_size": str(self._results),
            "filter_dead": "true",
            "mature": "false",
        }
        headers = {"Accept": "application/json", "User-Agent": "TrilingualDictionaryImageCandidates/0.2"}
        payload = _request_json(OPENVERSE_ENDPOINT, params, headers, self._timeout)

        for item in payload.get("results") or []:
            url = item.get("url") or ""
            if not url.startswith("https://"):
                continue
            licence = normalise_licence(item.get("license"))
            if not licence_is_allowed(licence):
                continue
            return Candidate(
                url=url,
                thumb_url=item.get("thumbnail") or url,
                licence=licence,
                creator=_plain(item.get("creator")),
                source_page=item.get("foreign_landing_url") or "",
                provider="openverse",
            )
        return None


class WikipediaProvider:
    """Wikipedia lead image for a headword, licence verified through Commons.

    A glossary word is often an encyclopedic concept (``petri dish``, ``reindeer``,
    ``Jurassic``), and Wikipedia's summary endpoint returns its lead image where a
    Commons file search returns nothing usable. The thumbnail URL is not evidence
    of licensing on its own, so the file name is resolved back through the Commons
    API and the same ``ALLOWED_LICENCES`` gate decides. Unverifiable images are
    dropped, never assumed free.
    """

    _THUMB = re.compile(
        r"/(?:commons|wikipedia/(?:commons|[a-z-]+))/"
        r"(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/]+?)(?:/[^/]+)?$"
    )

    def __init__(self, contact: str = "", timeout: float = 15.0, languages: Sequence[str] = ("zh", "en")) -> None:
        self._contact = contact
        self._timeout = timeout
        self._languages = tuple(languages)

    def user_agent(self) -> str:
        contact = self._contact or "contact not configured"
        return (
            "TrilingualDictionaryImageCandidates/0.2 "
            f"(dictionary image review; contact: {contact}) python-urllib"
        )

    @staticmethod
    def _file_name(thumb_url: str) -> str:
        path = urllib.parse.urlparse(thumb_url).path
        match = WikipediaProvider._THUMB.search(path)
        if not match:
            return ""
        return urllib.parse.unquote(match.group(1))

    def _summary(self, word: str, lang: str) -> dict:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(word)}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent()})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code <= 599:
                raise Retryable(f"HTTP {exc.code}") from exc
            return {}
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise Retryable(f"connection: {exc}") from exc

    def _licence_for_file(self, file_name: str) -> tuple[str, str, str]:
        """Return (licence, creator, source_page) for a Commons file, or blanks."""
        params = {
            "action": "query",
            "format": "json",
            "titles": f"File:{file_name}",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiextmetadatafilter": "LicenseShortName|License|Artist",
        }
        headers = {"User-Agent": self.user_agent(), "Accept": "application/json"}
        payload = _request_json(COMMONS_ENDPOINT, params, headers, self._timeout)
        pages = (payload.get("query") or {}).get("pages") or {}
        for page in (pages.values() if isinstance(pages, dict) else pages):
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            licence = normalise_licence(_meta(meta, "LicenseShortName") or _meta(meta, "License"))
            if not licence_is_allowed(licence):
                return "", "", ""
            return licence, _plain(_meta(meta, "Artist")), info.get("descriptionurl") or ""
        return "", "", ""

    def __call__(self, query: str) -> Candidate | None:
        for lang in self._languages:
            data = self._summary(query, lang)
            thumb = (data.get("thumbnail") or {}).get("source") or ""
            if not thumb:
                continue
            file_name = self._file_name(thumb)
            if not file_name:
                continue
            licence, creator, source_page = self._licence_for_file(file_name)
            if not licence:
                continue
            return Candidate(
                url=thumb,
                thumb_url=thumb,
                licence=licence,
                creator=creator,
                source_page=source_page or f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(query)}",
                provider=f"wikipedia-{lang}",
            )
        return None


class ChainProvider:
    """Try providers in order and return the first candidate found.

    The rows that matter most are exactly the ones a single source fails on, so
    the chain is conservative: it never fabricates a result, and every candidate
    still passes the licence gate of the provider that produced it.
    """

    def __init__(self, providers: Sequence[tuple[str, Callable[[str], Candidate | None]]]) -> None:
        self._providers = list(providers)

    def __call__(self, query: str) -> Candidate | None:
        for _name, provider in self._providers:
            try:
                candidate = provider(query)
            except Retryable:
                raise
            except ProviderRowError:
                continue
            if candidate is not None:
                return candidate
        return None


class OfflineProvider:
    """Deterministic stand-in for tests; never touches the network."""
    def __init__(self, mapping: Mapping[str, Candidate | str | None]) -> None:
        self._mapping = dict(mapping)
        self.calls: list[str] = []

    def __call__(self, query: str) -> Candidate | None:
        self.calls.append(query)
        value = self._mapping.get(query)
        if value is None:
            return None
        if isinstance(value, Candidate):
            return value
        return Candidate(url=value, licence="cc0", provider="offline")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class Cache:
    """provider + normalised query + template version -> candidate or None."""

    def __init__(self, path: Path | None, template_version: str) -> None:
        self.path = path
        self.template_version = template_version
        self.data: dict[str, dict[str, str] | None] = {}
        self._dirty = False

    @staticmethod
    def normalise_query(query: str) -> str:
        return re.sub(r"\s+", " ", query.strip()).casefold()

    def key(self, provider: str, query: str) -> str:
        return f"{provider}|{self.template_version}|{self.normalise_query(query)}"

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, dict):
            self.data = entries

    def get(self, provider: str, query: str) -> object:
        return self.data.get(self.key(provider, query), _MISSING)

    def put(self, provider: str, query: str, candidate: Candidate | None) -> None:
        self.data[self.key(provider, query)] = candidate.as_cache() if candidate else None
        self._dirty = True

    def save(self) -> None:
        if not self.path or not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"template_version": self.template_version, "entries": self.data}
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=str(self.path.parent), suffix=".tmp"
        )
        try:
            with handle as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
            os.replace(handle.name, self.path)
        finally:
            if os.path.exists(handle.name):
                os.unlink(handle.name)
        self._dirty = False


def template_version(template: str, suffix: str, context_column: str | None) -> str:
    basis = f"{template}|{suffix}|{'ctx' if context_column else 'noctx'}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

class CsvProblem(ValueError):
    """A file the tool refuses to work with, reported without a traceback."""


def load_rows(
    path: Path, delimiter: str, encoding: str
) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter, restkey="\x00extras")
        if not reader.fieldnames:
            raise CsvProblem(f"{path.name}: no header row")

        raw_names = [str(name) for name in reader.fieldnames]
        fieldnames = [name.strip() for name in raw_names]
        if any(not name for name in fieldnames):
            raise CsvProblem(f"{path.name}: a header cell is empty")
        if len(set(fieldnames)) != len(fieldnames):
            raise CsvProblem(f"{path.name}: duplicate column names in header")

        # Header cells may carry padding; read by the original key and store
        # the cleaned name, so --column matches what the user sees in Excel.
        lookup = {raw: clean for raw, clean in zip(raw_names, fieldnames)}

        rows: list[dict[str, str]] = []
        extras_seen = 0
        for raw in reader:
            if "\x00extras" in raw:
                extras_seen += 1
            row = {}
            for raw_name, clean in lookup.items():
                value = raw.get(raw_name)
                row[clean] = "" if value is None else str(value)
            rows.append(row)
        if extras_seen:
            print(
                f"warning: {extras_seen} row(s) had more cells than the header; "
                "the extra cells were dropped",
                file=sys.stderr,
            )
    return fieldnames, rows


def write_rows(
    path: Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, str]],
    delimiter: str,
    encoding: str,
) -> None:
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(fieldnames), delimiter=delimiter, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def with_output_columns(fieldnames: Sequence[str]) -> list[str]:
    """Append the five columns, or keep an existing one in its place."""
    names = list(fieldnames)
    for column in OUTPUT_COLUMNS:
        if column not in names:
            names.append(column)
    return names


def blank_output(row: dict[str, str]) -> None:
    for column in OUTPUT_COLUMNS:
        row[column] = ""


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

def _strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _looks_english(text: str) -> bool:
    """English enough: mostly ASCII letters, or letters that only carry accents."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    ascii_share = sum(1 for ch in letters if ch.isascii()) / len(letters)
    if ascii_share >= 0.9:
        return True
    stripped = [ch for ch in _strip_diacritics(text) if ch.isalpha()]
    return bool(stripped) and all(ch.isascii() for ch in stripped) and not CJK.search(text)


def detect_english_column(
    fieldnames: Sequence[str], rows: Sequence[Mapping[str, str]], tolerance: float = 0.10
) -> str:
    """Pick the English column from cell content alone, never from the header.

    Headers like "英文" are legitimate. Scoring is the share of English cells;
    every column within `tolerance` of the best ratio is a finalist, and the
    finalist with the fewest mean tokens wins — a headword column beats a gloss
    column that is just as English. A genuine tie raises instead of guessing.
    """
    scored: list[tuple[float, float, str]] = []
    for name in fieldnames:
        if PINYIN_HEADER.search(name):
            continue  # a pinyin column is transliteration, never the English text
        values = [str(row.get(name) or "").strip() for row in rows]
        values = [value for value in values if value]
        if not values:
            continue
        ratio = sum(1 for value in values if _looks_english(value)) / len(values)
        mean_tokens = sum(len(value.split()) for value in values) / len(values)
        scored.append((ratio, mean_tokens, name))

    if not scored:
        raise ValueError("no column has English text; pass --column explicitly")

    best_ratio = max(score[0] for score in scored)
    if best_ratio < 0.5:
        raise ValueError("no column is predominantly English; pass --column explicitly")

    finalists = [score for score in scored if best_ratio - score[0] <= tolerance]
    finalists.sort(key=lambda score: (score[1], score[2]))

    if len(finalists) >= 2 and abs(finalists[0][1] - finalists[1][1]) < 0.25:
        raise ValueError(
            f"English column ambiguous between {[f[2] for f in finalists[:2]]}; pass --column"
        )
    return finalists[0][2]


# ---------------------------------------------------------------------------
# Query building + enrichment
# ---------------------------------------------------------------------------

def build_query(
    word: str,
    template: str = "{word}",
    suffix: str = "",
    context: str = "",
) -> str:
    """One query string: template on the word, gloss appended to disambiguate."""
    if "{word}" in template:
        query = template.replace("{word}", word)
    else:
        query = f"{template} {word}".strip()
    if "{context}" in query and context:
        query = query.replace("{context}", context)
    elif context and "{context}" not in template:
        query = f"{query} {context}".strip()
    if suffix:
        query = f"{query} {suffix}".strip()
    return re.sub(r"\s+", " ", query).strip()


def enrich_rows(
    rows: list[dict[str, str]],
    column: str,
    provider: Callable[[str], Candidate | None],
    *,
    provider_name: str = "",
    template: str = "{word}",
    context_column: str | None = None,
    suffix: str = "",
    cache: Cache | None = None,
    qps: float = 1.0,
    max_retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
    max_queries: int | None = None,
    retry_misses: bool = False,
    persist_every: int = PERSIST_EVERY,
    start: int = 0,
    limit: int | None = None,
    checkpoint: Callable[[], None] | None = None,
    save_every: int = 25,
) -> list[tuple[int, str, str]]:
    """Fill the five output columns for the selected window.

    Returns (1-based row number, query, reason) for every row that ended blank.
    Rows outside the window are blanked too, so nothing stale survives a resume.
    Raises FatalProviderError for auth/quota failures — the caller writes the
    partial output and exits 3.
    """
    for row in rows:
        blank_output(row)

    failures: list[tuple[int, str, str]] = []
    interval = 1.0 / qps if qps > 0 else 0.0
    budget = 0
    since_persist = 0
    last_call = 0.0

    window_end = len(rows) if limit is None else min(len(rows), start + limit)

    for index in range(start, window_end):
        # Durable progress: the caller rewrites the output CSV every N rows, so a
        # dropped connection loses at most one interval instead of the whole run.
        if checkpoint and save_every and (index - start) and (index - start) % save_every == 0:
            checkpoint()
        row = rows[index]
        word = str(row.get(column) or "").strip()
        if not word:
            failures.append((index + 1, "", "empty cell"))
            continue

        context = ""
        if context_column:
            context = str(row.get(context_column) or "").strip()
        query = build_query(word, template, suffix, context)

        searchable, skip_reason = query_is_searchable(query)
        if not searchable:
            failures.append((index + 1, query, skip_reason))
            log(f"[{index + 1}] skip    {query}  ({skip_reason})")
            continue

        cached = cache.get(provider_name, query) if cache else _MISSING
        if cached is not _MISSING and cached is not None:
            candidate = Candidate.from_cache(cached)
            _apply(row, candidate)
            log(f"[{index + 1}] cached  {query}")
            continue
        if cached is None and not retry_misses:
            log(f"[{index + 1}] cached miss  {query}")
            continue

        if max_queries is not None and budget >= max_queries:
            failures.append((index + 1, query, "budget exhausted: not queried"))
            continue

        wait = interval - (time.monotonic() - last_call)
        if wait > 0:
            sleep(wait)

        candidate: Candidate | None = None
        failed = False
        reason = ""
        delay = 1.0

        for attempt in range(max_retries + 1):
            budget += 1
            try:
                candidate = provider(query)
                break
            except FatalProviderError:
                if cache is not None:
                    cache.save()
                raise
            except Retryable as exc:
                reason = str(exc)
                if attempt >= max_retries:
                    failed = True
                    break
                sleep(exc.retry_after or delay)
                delay *= 2
            except ProviderRowError as exc:
                reason = str(exc)
                failed = True
                break
            except json.JSONDecodeError as exc:
                reason = f"malformed JSON: {exc}"
                failed = True
                break

        last_call = time.monotonic()

        if failed:
            failures.append((index + 1, query, reason))
            log(f"[{index + 1}] failed  {query}  ({reason})")
            continue

        if candidate is None:
            failures.append((index + 1, query, "no licence-compliant image"))
            log(f"[{index + 1}] none    {query}")
            if cache is not None:
                cache.put(provider_name, query, None)
            continue

        _apply(row, candidate)
        if cache is not None:
            cache.put(provider_name, query, candidate)
        log(f"[{index + 1}] ok      {query}  [{candidate.licence}]")

        since_persist += 1
        if cache is not None and persist_every and since_persist >= persist_every:
            cache.save()
            since_persist = 0

    if cache is not None:
        cache.save()
    return failures


def _apply(row: dict[str, str], candidate: Candidate) -> None:
    row[IMAGE_COLUMN] = candidate.url
    row[IMAGE_LICENCE_COLUMN] = candidate.licence
    row[IMAGE_CREATOR_COLUMN] = candidate.creator
    row[IMAGE_SOURCE_PAGE_COLUMN] = candidate.source_page
    row[IMAGE_PROVIDER_COLUMN] = candidate.provider


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _delimiter(value: str) -> str:
    return "\t" if value == "\\t" else value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add review-only image candidates (with licence metadata) to a CSV."
    )
    parser.add_argument("input", type=Path, help="source CSV")
    parser.add_argument("output", type=Path, help="destination CSV (must not exist unless --force)")
    parser.add_argument("--column", help="English text column; detected when omitted")
    parser.add_argument("--delimiter", default=",", type=_delimiter, help="default ','; '\\t' allowed")
    parser.add_argument("--encoding", default="utf-8-sig", help="default utf-8-sig")
    parser.add_argument("--provider", choices=("commons", "openverse", "wikipedia", "chain"),
                        default="commons")
    parser.add_argument("--contact", default=os.environ.get("IMAGE_LOOKUP_CONTACT", ""),
                        help="contact for the Wikimedia User-Agent (or IMAGE_LOOKUP_CONTACT)")
    parser.add_argument("--query-template", default="{word}", help="default '{word}'")
    parser.add_argument("--query-suffix", default="", help="appended to every query")
    parser.add_argument("--context-column", help="e.g. the gloss column, appended to the query")
    parser.add_argument("--qps", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-queries", type=int, help="hard budget of network calls this run")
    parser.add_argument("--start", type=int, default=0, help="skip the first N rows (resume)")
    parser.add_argument("--limit", type=int, default=0, help="process only N rows; 0 = all")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--retry-misses", action="store_true", help="re-query cached misses")
    parser.add_argument("--save-every", type=int, default=25,
                        help="rewrite the output CSV every N rows (0 disables checkpointing)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output")
    parser.add_argument("--dry-run", action="store_true", help="print queries; spend nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 2
    if args.input.resolve() == args.output.resolve():
        print("refusing to overwrite the input file; choose another output", file=sys.stderr)
        return 2
    if args.output.exists() and not args.force:
        print(f"output exists: {args.output} (pass --force to overwrite)", file=sys.stderr)
        return 2
    if args.start < 0 or args.limit < 0:
        print("--start and --limit must not be negative", file=sys.stderr)
        return 2

    try:
        fieldnames, rows = load_rows(args.input, args.delimiter, args.encoding)
    except UnicodeDecodeError as exc:
        print(f"cannot decode {args.input} as {args.encoding}: {exc.reason}", file=sys.stderr)
        return 2
    except csv.Error as exc:
        print(f"malformed CSV in {args.input}: {exc}", file=sys.stderr)
        return 2
    except CsvProblem as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.limit:
        window = rows[args.start : args.start + args.limit]
        check_rows = window
    else:
        window = rows[args.start :]
        check_rows = window

    if not check_rows:
        print(f"warning: --start {args.start} is past the end ({len(rows)} rows)", file=sys.stderr)

    try:
        column = args.column or detect_english_column(fieldnames, check_rows or rows)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if column not in fieldnames:
        print(f"column {column!r} is not in the header: {fieldnames}", file=sys.stderr)
        return 2

    queries = [
        build_query(
            str(row.get(column) or "").strip(),
            args.query_template,
            args.query_suffix,
            str(row.get(args.context_column) or "").strip() if args.context_column else "",
        )
        for row in window
    ]

    version = template_version(args.query_template, args.query_suffix, args.context_column)
    cache = Cache(args.cache if args.cache else None, version)
    cache.load()

    if args.dry_run:
        print(f"rows={len(rows)} window={len(window)} (start={args.start}) column={column!r}")
        print(f"provider={args.provider} template={args.query_template!r} version={version}")
        for number, query in enumerate(queries[:10], start=1):
            print(f"  {number}. {query or '(empty)'}")
        needed = 0
        for query in queries:
            if not query:
                continue
            cached = cache.get(args.provider, query)
            if cached is _MISSING or (cached is None and args.retry_misses):
                needed += 1
        if args.max_queries:
            needed = min(needed, args.max_queries)
        print(f"estimated network calls after cache: {needed}")
        print("dry run: nothing written")
        return 0

    if args.provider in ("commons", "chain", "wikipedia"):
        commons = CommonsProvider(contact=args.contact)
        wiki = WikipediaProvider(contact=args.contact)
        if not args.contact:
            print(
                "warning: no --contact given; Wikimedia's User-Agent policy asks for one",
                file=sys.stderr,
            )
    if args.provider == "commons":
        provider = commons
    elif args.provider == "wikipedia":
        provider = wiki
    elif args.provider == "chain":
        provider = ChainProvider([("commons", commons), ("wikipedia", wiki)])
    else:
        provider = OpenverseProvider()

    if args.max_queries is not None and args.max_queries < 0:
        print("--max-queries must not be negative", file=sys.stderr)
        return 2

    fieldnames = with_output_columns(fieldnames)
    started = time.time()

    def checkpoint() -> None:
        """Atomic, resumable mid-run save: write to a temp file, then replace."""
        tmp = args.output.with_suffix(args.output.suffix + ".tmp")
        write_rows(tmp, fieldnames, rows, args.delimiter, args.encoding)
        os.replace(tmp, args.output)
        filled = sum(1 for row in rows if row.get(IMAGE_COLUMN))
        print(f"  checkpoint: {filled} rows with a candidate", file=sys.stderr)

    try:
        failures = enrich_rows(
            rows,
            column,
            provider,
            provider_name=args.provider,
            template=args.query_template,
            context_column=args.context_column,
            suffix=args.query_suffix,
            cache=cache,
            qps=args.qps,
            max_retries=args.max_retries,
            max_queries=args.max_queries,
            retry_misses=args.retry_misses,
            start=args.start,
            limit=args.limit or None,
            checkpoint=checkpoint,
            save_every=args.save_every,
        )
    except FatalProviderError as exc:
        cache.save()
        write_rows(args.output, fieldnames, rows, args.delimiter, args.encoding)
        print(f"provider refused the run: {exc}", file=sys.stderr)
        print(f"partial output written to {args.output}; stopped before any further row", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        cache.save()
        write_rows(args.output, fieldnames, rows, args.delimiter, args.encoding)
        print("\ninterrupted: partial output and cache written", file=sys.stderr)
        return 130

    cache.save()
    write_rows(args.output, fieldnames, rows, args.delimiter, args.encoding)

    elapsed = time.time() - started
    filled = sum(1 for row in rows if row.get(IMAGE_COLUMN))
    print(
        f"\nwrote {args.output}: {len(rows)} rows, {filled} with a candidate, "
        f"{len(failures)} blank, {elapsed:.1f}s"
    )
    print(
        "review material only: these are unlicensed-by-this-tool candidates — "
        "build_image_index.py's licence gate decides what ships, never concept_images"
    )
    if failures:
        print(f"{len(failures)} row(s) without a candidate:")
        for index, query, reason in failures[:20]:
            print(f"  row {index}: {query or '(empty)'} — {reason}")
        if len(failures) > 20:
            print(f"  ... {len(failures) - 20} more")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
