# AUTH-SCHEMA.md — Phase 1: identity schema, RLS, retention

Status: **migrations written, executed and rolled back against a scratch
PostgreSQL; not applied to a Supabase project.** Phase 1 is "verified locally,
not deployed". Real-project verification is blocked on credentials, see §5.
Ordering and the human-only steps are in `docs/HUMAN_TODO.md`. Web is deferred
and the product is mobile-only for now (A20/A21).

Files: `supabase/migrations/2026111309*.sql` (4 files, applied in filename
order). The migrations assume Supabase primitives — the `auth` schema, the
`anon` / `authenticated` / `service_role` roles and `auth.uid()` — and refuse to
run on a bare PostgreSQL. That assumption is deliberate: adding fallbacks for
other environments would make the policies mean something different from what
they mean on Supabase.

---

## 1. Identity model

Supabase Auth owns everything that authenticates a person: password hashing,
6-digit code issuance and expiry, JWT signing, refresh rotation and session
revocation. No password, code or token column exists in our schema — those only
live in `auth.*`, which the client never touches directly.

Our tables hold only what Supabase Auth does not model:

| Table | Rows hold | Client access |
|---|---|---|
| `profiles` | username, display name, lifecycle status, locale, lockout state | **own row, read only** |
| `auth_challenges` | one row per emailed code: attempt budget, 10-minute expiry, email **hash** | none |
| `auth_rate_limits` | fixed-window counters per bucket (ip / user / device / email / endpoint) | none |
| `auth_lockouts` | escalating lockout state per subject | none |
| `security_events` | append-only audit trail, 30-day retention | none |
| `blocklist` | hashed identifiers with reason, expiry, and who decided | none |
| `security_proposals` | the advisory agent's report and proposed action | none |
| `reserved_usernames` | handles nobody may register | none |

`profiles.user_id` is the primary key and cascades from `auth.users`, so deleting
an identity deletes its profile and nothing can outlive its account.

## 2. Invariants enforced by the database, not by code

These are check constraints and unique indexes rather than application rules,
because a bug in the FastAPI layer must not be able to produce them:

| Invariant | Where |
|---|---|
| `status='active'` requires `activated_at` — a verified-but-unfinished signup can never be a usable account | `profiles_activated_chk` |
| Usernames are unique **case-insensitively** (`Anna` collides with `anna`) | `profiles_username_key` on `lower(username)` |
| One profile per email address | `profiles_email_key` on `lower(email)` |
| Username shape: 3–20 chars, `a-z 0-9 _ .` only | `profiles_username_chk` |
| An **agent-created** block cannot outlive 1 hour, whatever the agent code sends | `blocklist_agent_ttl_chk` |
| Event types are a closed list; severity 1–5 | `security_events_type_chk`, `security_events_severity_chk` |
| Event payloads stay under 4 KB — a log line is an observation, not a data store | `security_events_details_size_chk` |

The agent TTL check is the important one: "the agent may only block for an hour"
is enforced by Postgres, so a compromised or misbehaving agent cannot write a
permanent block even if the Python guard is bypassed.

## 3. Row Level Security

RLS is on for every table. Exactly one policy exists in the whole schema:

```sql
-- profiles_select_own: authenticated users read their own row, nothing else
using ((select auth.uid()) = user_id)
```

Everything else is deny-all: RLS on, **no policies**, and `revoke all` from
`anon` and `authenticated`. Writes to `profiles` (activation, lockout counters,
locale, last login) happen server-side with the service-role key. Grants are
written explicitly instead of inherited from Supabase default privileges, so a
table added later cannot silently become readable by `anon`.

The migration ends with the self-check query that must return zero rows: any
policy on a deny-all table means the file was misapplied.

## 4. Retention

| Data | Retention | Mechanism |
|---|---|---|
| `security_events` | 30 days | `purge_security_events()` |
| half-finished signups (`status='pending'`) | 24 hours | `purge_pending_accounts()` — deletes the profile **and** the `auth.users` row behind it |
| codes, rate-limit windows | 2 days | `purge_transient_rows()` |
| settled lockouts, expired blocks | 7 days after expiry | `purge_transient_rows()` |

Scheduling: migration 3 registers three `pg_cron` jobs **only if `pg_cron` is
already installed**; otherwise it raises a notice and the same three functions
are called by the FastAPI scheduler. A migration that hard-fails on a project
without `pg_cron` would block Phase 2 for no reason.

Deleting `auth.users` directly (rather than through the Admin API) is a
deliberate choice here: it is atomic with the profile row and cascades correctly.
It must run as a privileged role, which is why the function is `security definer`
and its `execute` is revoked from `anon` and `authenticated`.

## 5. What was verified, and how

### What the "scratch database" is, exactly

`supabase/tests/run_migration_checks.py` creates a database named
`auth_migration_check` on the local PostgreSQL instance the backend already
talks to (`postgresql://postgres:postgres@localhost:5432`), applies the four
migrations, runs the checks, applies the four rollbacks, then **drops the
database**. It refuses to run against a non-local host unless `--allow-remote`
is passed, because "create and drop a database" against a real Supabase
project is a destructive act performed by a test.

Because a bare PostgreSQL has no `auth` schema, the script stubs exactly three
Supabase primitives: `auth.users(id, email, created_at, raw_user_meta_data)`,
`auth.uid()` (reading `current_setting('test.uid')`, so a check can act as a
given user) and the `anon` / `authenticated` / `service_role` roles. No other
piece of Supabase is simulated: `pg_cron` is genuinely absent, which exercises
the migration's "extension missing" branch.

The project database, `trilingual_dictionary`, is never written to.

### Running the checks

```powershell
# from the repository root — one command
backend\.venv\Scripts\python.exe supabase\tests\run_migration_checks.py
```

Options: `--keep` leaves the database for inspection, `--dsn` overrides the
connection string, `--allow-remote` permits a non-local host (not for staging).

### Verified (20 checks, all passing)

- all four migrations execute; 31 reserved handles seeded; every table has RLS
  on; **exactly one** policy in `public`
- pending profile accepted; `status='active'` without `activated_at` **rejected**
- `Anna` then `anna` **rejected** as a duplicate
- a second pending row for one email **rejected** — no shadow identity can exist
- an agent block of 2 hours **rejected**; 40 minutes accepted
- unknown `event_type` **rejected**; `details` over 4 KB **rejected**
- `purge_pending_accounts()` removed a 25-hour-old pending signup together with
  its `auth.users` row, kept the fresh one, and **left a 40-day-old ACTIVE
  account untouched**
- an `authenticated` client **cannot insert** a pending profile (so an attacker
  cannot squat a signup row for someone else's address)
- an `authenticated` user reading `profiles` sees **only their own row**
- an `authenticated` client cannot read `security_events`, `blocklist`,
  `security_proposals` or `auth_rate_limits`
- `purge_security_events()` deletes the 31-day row and keeps the 29-day one
- deleting `auth.users` **cascades** to `profiles` (the DB half of account deletion)
- the four rollbacks remove every table, function and policy

### Not verified: real staging project

No Supabase project exists for this repository yet, and this machine holds no
credentials for one: `backend/.env` defines `SUPABASE_URL` and
`SUPABASE_JWT_SECRET` but both values are empty, and there is no
`SUPABASE_ANON_KEY` or `SUPABASE_SERVICE_ROLE_KEY` anywhere. Running this on a
real project therefore needs, from you:

1. the staging project URL,
2. the **anon** key (used by the client and by the JWT-scoped tests),
3. the **service-role** key (server only), and
4. the JWT signing mode — legacy HS256 secret, or asymmetric keys with a JWKS
   endpoint.

With those, the same script can run in "staging mode" against the real
project: apply the migrations with `supabase db push`, then run the RLS half
with the anon key and a real user JWT instead of the stubs. The script's checks
are already written against roles, so they only need a different connection
identity.

## 6. SMTP notes (setup, not code)

Supabase Auth sends the 6-digit code through the SMTP provider configured in
**Project → Authentication → Emails**, so the code path stays inside Supabase
and our backend never handles a code.

- Use a dedicated sending subdomain (`auth.<your-domain>`), then publish SPF,
  DKIM and DMARC before launch — `docs/HUMAN_TODO.md` lists this as a human step.
- Keep Supabase's own per-hour email limit **below** ours (5 emails/hour/address)
  so our limit is the one users actually hit; a provider limit that fires first
  produces a generic error that looks like a bug.
- Set the code expiry to 10 minutes to match `auth_challenges.expires_at`.
- The email template must not reveal whether the address already has an account:
  one template for signup and reset, wording "your code", never "welcome back".

## 7. Open decisions carried into Phase 2

- **JWT verification.** `backend/app/core/security.py` decodes HS256 with a
  shared secret. New Supabase projects sign with asymmetric keys and may not
  expose that secret; Phase 2 must verify via JWKS (or through the Supabase
  client) or every real token will return 401.
- **Refresh-token reuse detection** is Supabase's own session-family revocation;
  our job is to verify it and log `TOKEN_REUSE`, not to reimplement it.
- **Lockout storage.** `profiles.failed_login_count` / `lockout_until` hold the
  per-account ladder; `auth_lockouts` holds ip and device ladders. Both are
  consulted before a password check.
