# Phase 2.1 — operational closure checklist

Four items stand between "implementation complete" and "closed". Nothing else is
in scope. Each item is closed by evidence pasted next to it, not by a sentence
saying it was done.

## C1 — Remote CI on the pushed sha (S-04)

Status: **open, and not closable from the build machine.** No `gh` CLI is
installed and the repository API answers 404 to an unauthenticated caller.

To close:

```
# on a machine with repo access
gh workflow run contracts.yml --ref main
gh run list --workflow contracts.yml --limit 3
gh run view <run-id> --log-failed        # if it fails
```

Evidence to paste: run URL, head sha (must equal the pushed commit), job names,
per-job conclusion, duration. A local green suite is not a substitute.

## C2 — Go/no-go on the 5 quarantine candidates (S-03)

Candidates, measured read-only by `backend/tools/classify_script_mix.py`:

| sense | text | token | verdict |
| --- | --- | --- | --- |
| 59001 | शuai उपनाम | शuai | intra_token_mix |
| 66092 | केही आश्चर्य नै हoinu | हoinu | intra_token_mix |
| 112935 | बatti | बatti | intra_token_mix |
| 112963 | बatti | बatti | intra_token_mix |
| 170710 | दृढतापूर्वक पурсnu | पурсnu | intra_token_mix |

Not candidates (legitimate mixed content, must stay visible): 5090 `सूची अक्षर C`,
49650 `Zhuge Liang को सम्मान नाम`.

To close: an explicit decision line. If it is "quarantine all five", the mutation
must (a) run in one transaction, (b) copy the original text, rule, batch id and
timestamp into `quarantine_records`, (c) leave `senses.gloss_ne` untouched, (d) be
rehearsed on a copy first and reported with before/after counts.

## C3 — Fingerprint freeze

`FINGERPRINT_VERSION = 1`, definition in `schema.content_fingerprint` and
`tools/fingerprint.py`, pinned by 8 contract tests including separator forgery.
To close: state that v1 is frozen; any later change bumps the version and
re-measures every recorded fingerprint in the same commit.

## C4 — Shipped FTS asset stays untouched

`docs/ASSET-PINS.json` pins `dictionary.sqlite`
(`3f9e5f46…f171f3`) and `translations.db` (`2a6e4284…6cf036`);
`backend/tools/check_asset_pin.py` fails the suite if either changes. The 76-row
`fts_zh` hole remains accepted and shipped. To close this item *as a decision*:
state that the asset is unchanged now, and that any rebuild is a separate,
explicitly approved commit with the §5 evidence report.

## Out of scope for closure

Phase 1.5 (audit, backfills, quarantine writes, badge wiring), Phase 3 (any new
translation), schema freeze, and anything in `ISSUE-REGISTER.md` not listed above.
