# Human TODO — what only a person can do

Ordered by what unblocks the most. Every number is a row count read from the
database or a file in `review/`; every estimate says how it was derived.

## 1. Native Nepali review — the largest and most blocking item

| what | rows | file(s) | estimate |
|---|---|---|---|
| launch-set Nepali glosses (Tier 1+2) | 2,858 | `review/nepali-launch-part-01..06.xlsx` | ~95 h at 30 rows/h |
| remaining machine glosses outside the launch set | 387 | same topic, later batches | ~13 h |

- Who: a native Nepali speaker. A fluent second-language speaker is not enough
  for judging register and naturalness, which is what "reviewed" claims.
- How: read each row, fill `decision` (`approve` / `edit` + `edited_text` /
  `delete`). Blank means unreviewed and is never treated as approval.
- Apply with `python tools/import_review.py --file review/nepali-launch-part-01.xlsx --dry-run`
  first, then without `--dry-run`. `approve` sets `ne_status = 'reviewed'`.
- Practical advice: do one 500-row file end to end first and check the import
  report before committing to the rest.

## 2. Chinese high-frequency definitions

| what | rows | file(s) | estimate |
|---|---|---|---|
| Tier 1+2 entries whose Wiktionary gloss was routed to review | 5,140 | `review/chinese-highfreq-part-01..11.xlsx` | ~85 h at 60 rows/h |

- Who: a Chinese reader (native or near-native) who can spot a classical sense
  where a modern one is meant.
- Why it was not automated: for words like 的 the Wiktionary gloss is
  "白色；箭靶中心". Importing that would be worse than an empty field.

## 3. New words (1,348)

| what | rows | file(s) | estimate |
|---|---|---|---|
| 320 already human-written — confirm or reject | 320 | `review/new-words-part-01.xlsx` | ~10 h |
| 737 AI-filled — review English + Nepali | 737 | parts 1–2 | ~30 h |
| 291 still empty — need translation input | 291 | part 3 | ~8 h, after the provider decision in item 4 |

This topic also sets policy: a word not in CC-CEDICT is a judgement call ("is this
standard Mandarin?"). Decide once, at the top of the file, and apply consistently.

## 4. Choose and pay for an AI provider

- Status: **no working provider**. Groq is region-blocked (403/1010), Gemini
  times out, OpenRouter's free allowance is exhausted (402).
- Needed from you: vendor choice + API key put into environment variables
  (`PAID_PROVIDER_NAME`, `PAID_PROVIDER_URL`, `PAID_PROVIDER_KEY`,
  `PAID_PROVIDER_MODEL`, then `AI_ALLOW_PAID=true`). Never commit the key.
- Verify after wiring: `python backend/tools/provider_health.py` must print
  `working` for that provider before the generator is re-run.
- Unblocks: the 291 pending new words, and example-sentence generation.

## 5. Legal review of the drafts

- `CREDITS.md`, `PRIVACY_POLICY.md`, `docs/PLAY_DATA_SAFETY.md`,
  `docs/IMAGE_AUDIT.md` — all marked DRAFT.
- Fill `[CONTACT_EMAIL]`, `[APP_NAME]`, `[COMPANY_LEGAL_NAME]`.
- Confirm CC BY-SA 4.0 obligations for a commercial store listing, and whether a
  `LICENSE-DATA` file must be shipped next to the app licence.
- Answer the three **DECISION NEEDED** items in `docs/PLAY_DATA_SAFETY.md`:
  cloud sync of favourites, device/IP counting claim, crash reporting.

## 6. Real-device test list (not run — no device was available here)

| # | scenario | pass criterion |
|---|---|---|
| 1 | low-end phone (2 GB RAM), first launch | progress screen appears, unpack completes, search works; no OOM |
| 2 | device with < 120 MB free before first launch | clear "needs ~100 MB" message, retry button works, **no partial file left** |
| 3 | kill the app mid-unpack, relaunch | recovers (stale `.part` discarded), second attempt succeeds |
| 4 | upgrade from the previous build | favourites, history and AI results intact; dictionary content is the new one |
| 5 | airplane mode | search, entry view, images (if cached) work; AI actions show the honest "not found yet" |
| 6 | rotate + background/foreground on an entry screen | no crash, state kept |
| 7 | traditional-character input on a device without a Chinese IME | simplified result returned |

## 7. Store listing and submission

1. Fill the Data Safety form from `docs/PLAY_DATA_SAFETY.md`.
2. Attach the privacy policy URL once published.
3. Screenshots from the real-device run above (item 6), not from a simulator.
4. Release notes must state that machine translations are labelled as such.
5. Rollout: internal → closed → production, one build at a time; the asset
   unpack path is the highest-risk change in this release.

## Commands to run first

```powershell
# from the repo root
backend\.venv\Scripts\python.exe backend\tools\check.py        # full pipeline
backend\.venv\Scripts\python.exe backend\tools\check.py --fast # backend only
backend\.venv\Scripts\python.exe backend\tools\metrics.py       # current numbers
backend\.venv\Scripts\python.exe backend\tools\backup_db.py     # backup + checksum
```

`make` targets exist for the same four commands if `make` is installed.
