"""Behaviour of tools/enrich_csv_images.py — no network, no quota, no real CSV.

The load-bearing parts are the licence gate, the column choice and the failure
bookkeeping: a workbook tool that silently leaves rows blank, or that lets a
non-commercial image through, is worse than no tool at all.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.enrich_csv_images import (
    ALLOWED_LICENCES,
    IMAGE_COLUMN,
    IMAGE_CREATOR_COLUMN,
    IMAGE_LICENCE_COLUMN,
    IMAGE_PROVIDER_COLUMN,
    IMAGE_SOURCE_PAGE_COLUMN,
    OUTPUT_COLUMNS,
    Cache,
    Candidate,
    FatalProviderError,
    OfflineProvider,
    Retryable,
    blank_output,
    build_query,
    detect_english_column,
    enrich_rows,
    load_rows,
    main,
    normalise_licence,
    template_version,
    with_output_columns,
    write_rows,
)


ROWS = [
    {"word": "apple", "hanzi": "苹果", "pinyin": "píngguǒ", "meaning": "a round fruit"},
    {"word": "moon", "hanzi": "月亮", "pinyin": "yuèliàng", "meaning": "the satellite of earth"},
    {"word": "", "hanzi": "空", "pinyin": "", "meaning": "missing english cell"},
]

APPLE = Candidate(
    url="https://upload.wikimedia.org/apple.jpg",
    thumb_url="https://upload.wikimedia.org/apple_320.jpg",
    licence="cc0",
    creator="Someone",
    source_page="https://commons.wikimedia.org/wiki/File:Apple.jpg",
    provider="commons",
)


def _cache() -> Cache:
    return Cache(None, template_version("{word}", "", None))


def _quiet(**_kwargs):
    return {"sleep": lambda _s: None, "log": lambda _m: None}


# ---------------------------------------------------------------------------
# Licence gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CC0 1.0 Universal", "cc0"),
        ("CC0", "cc0"),
        ("CC BY 4.0", "cc by"),
        ("by", "cc by"),
        ("cc-by-sa 3.0", "cc by-sa"),
        ("Public domain", "public domain"),
        ("pdm", "public domain"),
        ("CC BY-NC 4.0", ""),
        ("GFDL", ""),
        ("", ""),
    ],
)
def test_normalise_licence(raw: str, expected: str):
    assert normalise_licence(raw) == expected


def test_every_allowed_licence_passes_the_shipped_gate():
    """ALLOWED_LICENCES must not drift from build_image_index's regex."""
    pytest.importorskip("PIL")
    from tools.build_image_index import ALLOWED_LICENCE

    for licence in ALLOWED_LICENCES:
        assert ALLOWED_LICENCE.match(licence), f"{licence} is rejected by build_image_index"


def test_a_non_commercial_candidate_is_dropped():
    candidate = Candidate(url="https://x/y.jpg", licence="cc by-nc")
    assert not normalise_licence(candidate.licence)


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

def test_english_column_by_content_only():
    """Headers are never required to be ASCII: '英文' is a normal header."""
    rows = [
        {"英文": "apple", "中文": "苹果"},
        {"英文": "moon", "中文": "月亮"},
    ]

    assert detect_english_column(list(rows[0].keys()), rows) == "英文"


def test_headword_beats_the_gloss_column():
    fieldnames = ["word", "hanzi", "pinyin", "meaning"]

    assert detect_english_column(fieldnames, ROWS) == "word"


def test_accepts_a_latin_word_with_an_accent():
    rows = [{"word": "café", "hanzi": "咖啡馆"}, {"word": "naïve", "hanzi": "天真"}]

    assert detect_english_column(["word", "hanzi"], rows) == "word"


def test_pinyin_header_is_never_chosen():
    rows = [
        {"english": "apple", "pinyin": "píngguǒ"},
        {"english": "moon", "pinyin": "yuèliàng"},
    ]
    assert detect_english_column(["english", "pinyin"], rows) == "english"

    only_pinyin = [{"pinyin": "píngguǒ"}, {"pinyin": "yuèliàng"}]
    with pytest.raises(ValueError, match="English"):
        detect_english_column(["pinyin"], only_pinyin)


def test_tolerance_prefers_fewer_words():
    rows = [
        {"head": "apple", "gloss": "a round fruit that grows on trees"},
        {"head": "moon", "gloss": "the natural satellite of the earth"},
    ]

    assert detect_english_column(["head", "gloss"], rows) == "head"


def test_genuine_tie_raises():
    with pytest.raises(ValueError, match="ambiguous"):
        detect_english_column(["a", "b"], [{"a": "cat", "b": "dog"}])


def test_non_english_sheet_raises():
    rows = [{"hanzi": "苹果", "pinyin": "píngguǒ"}]

    with pytest.raises(ValueError, match="predominantly English"):
        detect_english_column(["hanzi", "pinyin"], rows)


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------

def test_query_uses_template_context_and_suffix():
    assert build_query("bank") == "bank"
    assert build_query("bank", "{word} photo") == "bank photo"
    assert build_query("bank", "{word}", "photo", "river edge") == "bank river edge photo"
    assert build_query("bank", "{word} {context}", "photo", "river edge") == "bank river edge photo"


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def test_every_row_ends_with_every_output_column():
    rows = [dict(row) for row in ROWS]
    provider = OfflineProvider({"apple": APPLE})

    failures = enrich_rows(rows, "word", provider, provider_name="offline", **_quiet())

    for row in rows:
        for column in OUTPUT_COLUMNS:
            assert column in row
    assert rows[0][IMAGE_LICENCE_COLUMN] == "cc0"
    assert rows[0][IMAGE_CREATOR_COLUMN] == "Someone"
    assert rows[0][IMAGE_SOURCE_PAGE_COLUMN] == APPLE.source_page
    assert rows[0][IMAGE_PROVIDER_COLUMN] == "commons"
    assert rows[1][IMAGE_COLUMN] == ""
    assert [(index, reason) for index, _q, reason in failures] == [
        (2, "no licence-compliant image"),
        (3, "empty cell"),
    ]


def test_stale_values_are_cleared_before_each_row():
    rows = [{"word": "", "image_link": "https://old/thing.jpg"}]
    blank_output(rows[0])

    enrich_rows(rows, "word", OfflineProvider({}), provider_name="offline", **_quiet())

    assert rows[0][IMAGE_COLUMN] == ""


def test_cache_hit_costs_no_second_query():
    provider = OfflineProvider({"apple": APPLE})
    cache = _cache()

    first = [{"word": "apple"}]
    enrich_rows(first, "word", provider, provider_name="offline", cache=cache, **_quiet())

    second = [{"word": "  APPLE "}]
    enrich_rows(second, "word", provider, provider_name="offline", cache=cache, **_quiet())

    assert provider.calls == ["apple"]
    assert second[0][IMAGE_COLUMN] == APPLE.url


def test_a_miss_is_cached_and_skipped_unless_retry_misses():
    provider = OfflineProvider({})
    cache = _cache()

    enrich_rows([{"word": "unicorn"}], "word", provider, provider_name="offline", cache=cache, **_quiet())
    enrich_rows([{"word": "unicorn"}], "word", provider, provider_name="offline", cache=cache, **_quiet())
    assert provider.calls == ["unicorn"]

    enrich_rows(
        [{"word": "unicorn"}], "word", provider, provider_name="offline",
        cache=cache, retry_misses=True, **_quiet(),
    )
    assert provider.calls == ["unicorn", "unicorn"]


def test_retryable_is_retried_then_succeeds():
    attempts = {"n": 0}

    def provider(_query: str) -> Candidate:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Retryable("HTTP 503")
        return APPLE

    rows = [{"word": "river"}]
    failures = enrich_rows(rows, "word", provider, provider_name="offline", **_quiet())

    assert failures == []
    assert rows[0][IMAGE_COLUMN] == APPLE.url


def test_a_fatal_error_stops_the_run():
    def provider(_query: str) -> Candidate:
        raise FatalProviderError("HTTP 401: invalid token")

    rows = [{"word": "apple"}, {"word": "moon"}]
    with pytest.raises(FatalProviderError):
        enrich_rows(rows, "word", provider, provider_name="offline", **_quiet())

    assert all(row[IMAGE_COLUMN] == "" for row in rows)


def test_budget_stops_further_network_calls():
    provider = OfflineProvider({"apple": APPLE, "moon": APPLE})
    rows = [{"word": "apple"}, {"word": "moon"}, {"word": "river"}]

    failures = enrich_rows(
        rows, "word", provider, provider_name="offline", max_queries=1, **_quiet()
    )

    assert provider.calls == ["apple"]
    assert rows[0][IMAGE_COLUMN] == APPLE.url
    assert [(index, reason) for index, _q, reason in failures][0] == (2, "budget exhausted: not queried")


def test_window_processes_only_that_range_but_rows_keep_their_shape():
    rows = [{"word": "apple"}, {"word": "moon"}, {"word": "river"}]
    provider = OfflineProvider({"apple": APPLE, "moon": APPLE, "river": APPLE})

    enrich_rows(
        rows, "word", provider, provider_name="offline", start=1, limit=1, **_quiet()
    )

    assert provider.calls == ["moon"]
    assert rows[0][IMAGE_COLUMN] == ""
    assert rows[1][IMAGE_COLUMN] == APPLE.url
    assert rows[2][IMAGE_COLUMN] == ""


def test_context_column_is_appended_to_the_query():
    provider = OfflineProvider({"bank river edge": APPLE})
    rows = [{"word": "bank", "meaning": "river edge"}]

    failures = enrich_rows(
        rows, "word", provider, provider_name="offline",
        context_column="meaning", **_quiet(),
    )

    assert provider.calls == ["bank river edge"]
    assert failures == []


# ---------------------------------------------------------------------------
# CSV handling
# ---------------------------------------------------------------------------

def test_short_and_long_rows_are_normalised_before_any_query(tmp_path: Path):
    source = tmp_path / "ragged.csv"
    source.write_text(
        "word,hanzi,meaning\n"
        "apple,苹果\n"
        "moon,月亮,the satellite,extra cell\n",
        encoding="utf-8-sig",
    )

    fieldnames, rows = load_rows(source, ",", "utf-8-sig")

    assert fieldnames == ["word", "hanzi", "meaning"]
    assert rows[0]["meaning"] == ""
    assert rows[1]["meaning"] == "the satellite"
    assert set(rows[1]) == {"word", "hanzi", "meaning"}


def test_duplicate_headers_are_refused(tmp_path: Path):
    source = tmp_path / "dupe.csv"
    source.write_text("word,word\napple,apple\n", encoding="utf-8-sig")

    with pytest.raises(ValueError, match="duplicate"):
        load_rows(source, ",", "utf-8-sig")


def test_output_columns_are_appended_once_and_kept_in_place():
    assert with_output_columns(["word"]) == ["word", *OUTPUT_COLUMNS]
    assert with_output_columns(["word", "image_link"]) == ["word", "image_link", *(c for c in OUTPUT_COLUMNS if c != "image_link")]


def test_write_rows_ignores_cells_that_are_not_in_the_header(tmp_path: Path):
    target = tmp_path / "out.csv"
    rows = [{"word": "apple", IMAGE_COLUMN: "https://x/apple.jpg", "junk": "drop me"}]

    write_rows(target, ["word", IMAGE_COLUMN], rows, ",", "utf-8-sig")

    assert target.read_text(encoding="utf-8-sig").splitlines() == [
        "word,image_link",
        "apple,https://x/apple.jpg",
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_source(path: Path) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["word", "hanzi", "meaning"])
        writer.writeheader()
        writer.writerows(
            [
                {"word": "apple", "hanzi": "苹果", "meaning": "a round fruit"},
                {"word": "moon", "hanzi": "月亮", "meaning": "the satellite"},
            ]
        )
    return path


def test_cli_refuses_to_overwrite_an_existing_output(tmp_path: Path, capsys):
    source = _write_source(tmp_path / "in.csv")
    target = tmp_path / "out.csv"
    target.write_text("keep me", encoding="utf-8")

    code = main([str(source), str(target)])

    assert code == 2
    assert "--force" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "keep me"


def test_cli_refuses_to_overwrite_the_input(tmp_path: Path):
    source = _write_source(tmp_path / "in.csv")

    assert main([str(source), str(source)]) == 2


def test_cli_reports_a_bad_column_without_a_traceback(tmp_path: Path, capsys):
    source = _write_source(tmp_path / "in.csv")

    code = main([str(source), str(tmp_path / "out.csv"), "--column", "nope"])

    assert code == 2
    assert "not in the header" in capsys.readouterr().err


def test_dry_run_estimates_calls_after_cache_hits(tmp_path: Path, capsys):
    source = _write_source(tmp_path / "in.csv")
    cache_path = tmp_path / "cache.json"
    version = template_version("{word}", "", None)
    cache = Cache(cache_path, version)
    cache.load()
    cache.put("commons", "apple", APPLE)
    cache.save()

    code = main(
        [str(source), str(tmp_path / "out.csv"), "--cache", str(cache_path), "--dry-run"]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "estimated network calls after cache: 1" in out
    assert not (tmp_path / "out.csv").exists()
