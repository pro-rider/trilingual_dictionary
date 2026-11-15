# Public-release security record

Written when the repository was still private, before any visibility change. Its
purpose is that "there are no secrets in this repo" stops being a sentence someone
typed in chat and becomes a check anyone can re-run.

Repo: `https://github.com/pro-rider/trilingual_dictionary` · branch audited:
`character-panel` @ `4a722c6` · audit date: 2026-11-15.

## 1. What is deliberately NOT in the repository

| kept out | how | why it matters |
| --- | --- | --- |
| `backend/.env` (live values) | `.gitignore` → `!! backend/.env` | holds provider keys and the Supabase service-role key |
| `backend/.venv/` | ignored | 1 GB of third-party code, not ours to publish |
| `assets/data/dictionary.sqlite`, `.gz` | ignored | build artefact, reproducible from CC-CEDICT |
| `assets/images/detail/`, `manifest_v2_*.jsonl` | ignored | scraped image payloads, licensing per-image |
| `stroke_work/` (102.2 MB, 9,605 files) | ignored as of `5a7a57c` | raw upstream `hanzi-writer-data` package + Unihan dumps; re-downloadable via the recorded checksums |
| `android/local.properties` | ignored | contains `sdk.dir` and a machine-local path |
| `*.jks` / `*.keystore` / `google-services.json` | none exist in the tree at all | nothing to leak by accident |

`.env` was **never** committed at any point: `git log --all --oneline -- "*.env"`
returns nothing, so no live credential is recoverable from history.

## 2. What the scans covered and what they found

Scope: all 92 commits and 1,876 objects across every branch, plus the working tree
(714 tracked files).

```
git rev-list --all --count                     → 92
git rev-list --all --objects | wc -l           → 1876
git ls-files | wc -l                           → 714
```

**Key-shaped strings, every revision of every branch:**

```
git grep -I -h -E "eyJhbGciOi[A-Za-z0-9_-]{10,}|sk-proj-[A-Za-z0-9]|sk-ant-[A-Za-z0-9]\
|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}|github_pat_|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY\
|postgres(ql)?://[^@\s]{0,40}:[^@\s]{4,}@|xoxb-|AKIA[0-9A-Z]{16}" $(git rev-list --all)
```

Result: **no match** (`git grep` exits 1 on no match). No JWT, no `sk-` key, no
service-account blob, no private key block, no credential-bearing database URL.

**Files ever added, any branch, that look sensitive by name:**

```
backend/.env.example
translation_agent/.env.example
backend/data/test_fixtures/dictionary_fixture.sqlite
```

`backend/.env.example` contains only placeholders — the single non-empty value is
`DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/...`, i.e.
localhost defaults. The tracked SQLite fixture was opened and inspected: 152
dictionary entries, 425 senses, 8 images, **no user, account, token or session
table**. It is dictionary data, not personal data.

**The `service_role` hits that a naive scan reports are all non-secrets:**

```
.github/workflows/contracts.yml:110  echo "SUPABASE_SERVICE_ROLE_KEY=$SERVICE_ROLE_KEY"   ← reads ${{ secrets.* }}
backend/.env.example:88             SUPABASE_SERVICE_ROLE_KEY=                          ← empty
backend/app/core/config.py:117      supabase_service_role_key: str = ""                 ← default empty
supabase/migrations/*.sql           grant ... to service_role                            ← a SQL role name
```

**One historical synthetic literal, already recorded rather than hidden:**
`.gitleaks.toml` allowlists commit `d41c037`, file
`backend/tests/test_ai_free_failover.py`, string `sk-live-SECRETSECRET1234` — a
fixture written to prove keys are redacted from router stats, later replaced by
`fixture-not-a-real-key-0000`. It was never a credential.

## 3. Limit of this audit

`gitleaks` was **not installed**, so the commit-level scan above is a hand-built
regex sweep, not a scanner with 150+ provider rules and entropy detection. It is
thorough for the key types this project would plausibly leak (OpenAI, Anthropic,
Google, GitHub, Supabase JWT, private keys, database URLs), but it is not a
substitute for the real tool. Run this before flipping visibility if you want the
stronger guarantee:

```
gitleaks git --redact -f json -r gitleaks-out.json .
```

The repo already ships `.gitleaks.toml` with default rules extends plus that one
narrow allowlist, so the command works as-is once the binary is on PATH.

## 4. What going public actually exposes

This is the part only the owner can accept. Nothing here is a secret in the
credential sense, but all of it becomes world-readable:

- **`backend/` (259 files)** — the whole FastAPI service: auth flows, rate limiting,
  lockout logic, the requirement that every spending AI route sits behind the shared
  secret, provider failover. Public source makes the attack surface enumerable,
  which is normal for open source but must be a deliberate choice.
- **`supabase/` (16 files)** — schema, RLS policies, rollup and retention SQL. RLS
  policy text is useful to an attacker probing for a missing grant, but publishing
  it is how the policies get reviewed.
- **`backend/data/test_fixtures/dictionary_fixture.sqlite`** — dictionary content,
  safe as inspected above, but it is a binary in the tree.
- **The stroke pack itself** (`assets/strokes/`) — Arphic-derived. If the main repo
  is public, it **is** a place users can obtain the modified data, so the APL
  §2(b) "designated place" obligation is satisfied and the separate small repo
  proposed as "option B" in `docs/LICENSE-ARPHIC.md` is no longer needed. That
  document's option table says option A is rejected; it must be rewritten to match
  reality before or at the moment of the flip, or it will be a false statement in
  public history.

## 5. Non-secret identifiers that would be published (cosmetic, fixable)

None of these is a credential. All are tidiness/privacy items:

| where | what |
| --- | --- |
| `docs/RELEASE.json:3,5,8` | `C:\Users\Administrator\Desktop\Dictionery\...` absolute paths |
| `project_guide.md:109` | device serial `R9ZY40T6LXA` |
| `translation_agent/docs/REPORT-2026-11-09-tasks-011-015.md:4` | hostname `XXSM-20260403WF` |
| `backend/tests/test_auth_account.py:24-25` | display-name fixture `"Surendra"` |
| `backend/tests/test_auth_phase2b.py:383` | `someone@gmail.com` (obviously fake) |
| `CONTRIBUTING.md:162`, `project_guide.md:578` | `pro-rider@users.noreply.github.com` (already the noreply form) |

Scrubbing the first four is a single commit if wanted. They reveal a machine
layout, not a secret.

## 6. Checklist before changing visibility

1. Decide whether `backend/` and `supabase/` are acceptable in public source (§4).
2. Rewrite `docs/LICENSE-ARPHIC.md` option table to state that the public repo is
   the designated place (§4), or keep the repo private and use the small separate
   repo instead.
3. Optionally scrub §5.
4. Run `gitleaks git --redact .` and require zero findings (§3).
5. Confirm GitHub secret scanning / push protection is enabled for the repo after
   it goes public — that is the durable control, not this one-time audit.

Nothing in this repository needs key rotation, because no key ever entered its
history. If a real key was ever pasted into a file on disk that was copied
somewhere else, that is outside what this audit can see.
