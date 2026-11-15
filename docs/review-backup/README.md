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