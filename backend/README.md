# Trilingual Dictionary — Backend (FastAPI)

Search **English or 中文**, returns meanings + aligned example sentences in
**English · 中文 · नेपाली**. Nepali is output-only.

## Run (v1, offline-first, no DB required)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs (Swagger).

## Endpoints (prefix `/api/v1`)

| Method & path | Purpose |
|---|---|
| `GET /health` | liveness |
| `POST /search` | `{q, lang: "en"\|"zh"}` → entry + senses + 3-language meanings |
| `POST /search/sentence` | `{sense_id, word}` → aligned EN/中文/नेपाली sentence |
| `GET /popular?limit=` | popular words |
| `GET /suggest?q=&lang=` | search suggestions |
| `POST /analyze/text` | `{text, lang}` → per-unit trilingual meanings (word / compound / phrase / idiom) + whole translation; AI fallback with `degraded` flag |
| `GET /providers` | LLM failover chain health & metrics |
| `GET /me` (Bearer JWT) | Supabase identity of the signed-in user |
| `GET/POST/DELETE /favorites` (JWT) | user's saved words (DB-backed) |
| `POST /feedback` (JWT) | report an error → review queue (DB-backed) |

## Text analysis

`POST /api/v1/analyze/text` is the "read a whole sentence" endpoint:

1. Chinese is segmented with **jieba** (`app/text_analysis/segmenter.py`); rare
   jieba n-gram merges (`今天天气`) are split back into real words, then curated
   units (成语, compounds) are re-merged. Latin text splits on whitespace.
2. Units are resolved offline first (curated phrase DB → dataset).
3. Everything still unknown goes to the AI in **one batched call** across the
   failover chain; matching is case-insensitive and adjacent units the model
   merges (`很` + `好` → `很好`) are accepted.
4. English/Chinese function words (`the`, `a`, `的`, `了`) are `kind=function`
   and never count as failures. `degraded=true` means a real content unit is
   missing.

## Tests & data integrity

```bash
pytest                       # 35 tests: API + auth + quality + text analysis
python -m scripts.validate_dataset.py   # every sense has 3 meanings + ≥1 reviewed example
```

## Supabase auth (optional)

Set `SUPABASE_URL` and `SUPABASE_JWT_SECRET` in `.env`. The Flutter app signs
in via Supabase Auth and sends its JWT as a `Bearer` token; this backend
verifies it with the project JWT secret (`app/core/security.py`) and never sees
your AI/secret keys. Favorites + feedback need PostgreSQL running.

## Data & review model

- v1 reads the canonical dataset at `data/seed/en_zh_ne.json` (single source of truth).
- `app/models/word.py` defines the SQLAlchemy models for the future PostgreSQL
  layer; seed with `python -m scripts.seed_database` after `docker compose up -d`.
- Nepali fields carry `meaning_ne_status`/`source`/`reviewed_by` and examples a
  `review_status` — only **approved** content is treated as correct (v2 spec).
- `app/ai/provider.py` routes through the failover chain (Groq → Gemini →
  OpenRouter, configurable in `.env`). AI output is marked `ai`/unreviewed and
  is never treated as authoritative. Keys stay on the server — never in the
  Flutter app.

## Order

Frontend (Flutter) is built first and runs fully offline. This backend adds
authoritative data + (later) AI sentences on top.
