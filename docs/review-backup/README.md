# review-backup

Snapshots of `review/*.csv`.

`review/*.csv` is ignored by git (`.gitignore` line 80), so these files would not
survive a checkout. This folder keeps a tracked copy of the decisions that drove
the stroke pack, so a diff of the CSVs is visible in history.

Refresh after any rebuild:

```powershell
python tools/build_stroke_pack.py            # rewrites review/*.csv
Copy-Item review\*.csv docs\review-backup\   # then commit the backup
```

The `decision` column is empty on purpose: these are review artifacts, not
decisions taken by the agent.

Current contents are the **top-3000** generation (2026-11-15): 123 differing
characters, 262 spot-check rows, 80 missing Han characters. The earlier top-1000
set (59 differences, 198 rows, 38 missing) remains in git history if the two need
comparing.

`test/stroke_review_captures_test.dart` reads the spot-check list from here when
`review/stroke_spot_check.csv` is absent — which is the normal case in CI, since
the folder above is regenerated locally precisely because `review/*.csv` is
ignored. This backup is therefore a hard dependency of a green CI run: delete the
CSV and the contact-sheet test fails rather than silently rendering nothing.