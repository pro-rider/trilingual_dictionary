# Blocked — things that could not be done, and exactly why

Every item here was attempted or deliberately deferred, with the reason stated in
terms of what was observed. Nothing in this file is a TODO dressed up as done.

## 1. Full AI translation of the 1,348 new words — BLOCKED (quota)

- Done: **1,057 / 1,348** rows have both an English and a Nepali value
  (320 from the earlier human-assisted batch, 737 from AI).
- Remaining: **291** rows are `pending_gloss` in `words3000_candidates`.

Why it stopped (measured 2026-11-12, `tools/provider_health.py`):

| provider | result |
|---|---|
| Groq | HTTP **403**, `error code: 1010` — region block. Permanent for this machine; retrying cannot help. |
| OpenRouter (free) | worked until the daily free allowance ran out, then HTTP **402** ("can only afford 617"), then SSL `UNEXPECTED_EOF_WHILE_READING` |
| Gemini | HTTP 503 / connection timeouts / 404 on the configured model names |

What unblocks it: a paid provider key (`PAID_PROVIDER_*` env vars exist, lane 21
is wired and off by default) **or** a free-tier reset. The generator is
repeatable — `python tools/gen_new_word_gloss.py --resume` picks up the 291
pending rows and never re-sends a completed one.

## 2. Example sentences for the launch set — BLOCKED (quota + licence)

- Done: pipeline + validator + 2 candidate rows.
- Missing: **14,567** of the 14,569 launch-set senses have no example.

Source order was honoured (licensed offline corpus → AI if a provider works →
leave empty). No licensed offline example corpus is present in the repository,
and the AI providers are down as above. Nothing was invented to fill the gap.

## 3. Chinese definitions for launch tiers 1 and 2 — DEFERRED to human review

- Coverage: tier 1 **0 / 7,447**, tier 2 **0 / 7,122**.

This is not a fault: the importer deliberately refuses to auto-import those
entries, because for high-frequency words the Wiktionary gloss lists classical
meanings first (的 → "白色；箭靶中心"). 5,140 such candidates are in
`review/chinese-highfreq-*.xlsx` waiting for a Chinese reader.

## 4. Nepali review — NOT POSSIBLE without a native speaker

- 3,245 machine Nepali glosses, 0 reviewed. A reviewer needs to be a native
  speaker; no automated substitute was attempted, because a machine checking a
  machine is not review.

## 5. Paid AI provider — HUMAN DECISION

- No vendor chosen, no key issued. `docs/HUMAN_TODO.md` lists what is needed.

## 6. Store submission and legal sign-off — HUMAN

- `CREDITS.md`, `PRIVACY_POLICY.md`, `docs/PLAY_DATA_SAFETY.md` are drafts with
  placeholders (`[CONTACT_EMAIL]`, `[APP_NAME]`, `[COMPANY_LEGAL_NAME]`).
- `docs/PLAY_DATA_SAFETY.md` has three **DECISION NEEDED** answers.

## 7. Known data defects left in place (documented, not fixed)

| defect | why it is not fixed here |
|---|---|
| `fts_zh` missing entry ids 123,597–123,672 (76 rows) | the 76 new entries were inserted after the last index build; the release DB ships the same gap. Adding them changes the index hash and the packed asset, which belongs in a rebuild that also re-runs the ranking suite. Recorded in `docs/RELEASE.json` and in the pin note. |
| image 7 has no thumbnail asset | needs a rebuild of that one thumbnail from its Wikimedia source; `tools/rebuild_missing_thumb.py` exists and fixed image 26, but image 7 has no recorded `detail_url` to fetch from — the row must be re-sourced first. |
| `{{zh-x|…}}` template wrapper inside 3,472 candidate example strings | those strings are candidate-only (never released) and Phase 5 requires review anyway; rewriting them silently would hide the problem from the reviewer. |
| 18 search-ranking defects | each one is a scoring change with its own risk; pinned as executable `xfail` with reasons in `docs/RANKING_KNOWN_DEFECTS.md`. |

## 8. Crash reporting and alert webhook — HUMAN/PRIVACY DECISION

- Hooks exist (`lib/core/diagnostics.dart` sink, `app/core/obs.py`
  `set_alert_hook`) but no SDK or endpoint is configured, because the Play
  Data Safety answer depends on it.
