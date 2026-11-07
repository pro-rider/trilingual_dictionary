# trilingual_dictionary

Flutter client for the Trilingual Dictionary — search or paste **English or 中文** and
read meanings + aligned example sentences in **English · 中文 · नेपाली**.

Full architecture, run commands, verification results and known gaps:
**[project_guide.md](project_guide.md)**.

## Quick start

```powershell
# 1. backend (FastAPI) — needs its own venv
cd ..\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 2. app
$env:Path = "C:\Windows\System32;C:\Windows;C:\Program Files\Git\cmd;C:\flutter\bin;$env:Path"
flutter run
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000   # Android emulator
```

The app works offline against the bundled dataset; search, analysis and the
trilingual "whole translation" use the backend when it is reachable.

## Checks

```powershell
flutter analyze   # no issues
flutter test      # 5 passed
```

## Layout

```
lib/
  app/        routing (go_router) + theme
  core/       normalizer, API/Supabase config, constants
  data/       Dio API client, repository, models
  features/   search · analyze · detail · history · favorites · auth · settings
assets/data/  offline dictionary seed
```
