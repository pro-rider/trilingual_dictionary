# AUTH-SCHEMA.md — Phase 1: identity schema, RLS, retention

Status: **migrations written and executed against a scratch PostgreSQL, not
applied to a Supabase project.** Phase 1 is "verified locally, not deployed".
Ordering and the human-only steps are in `docs/HUMAN_TODO.md`.

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

The four files were executed against a **scratch database** (`auth_migration_check`,
created and dropped by the verification script; the real project database was
never touched), with `auth.users`, `auth.uid()` and the three Supabase roles
stubbed because a bare PostgreSQL does not have them.

Passed:

- all four migrations execute; 31 reserved handles seeded; every table has RLS
  on; **exactly one** policy in `public`
- pending profile accepted; `status='active'` without `activated_at` **rejected**
- `Anna` then `anna` **rejected** as a duplicate
- an agent block of 2 hours **rejected**; 40 minutes accepted
- unknown `event_type` **rejected**
- `purge_pending_accounts()` removed a 25-hour-old pending signup together with
  its `auth.users` row, and kept the fresh one
- `purge_security_events()` and `purge_transient_rows()` execute

Not verified, because it requires the real project: SMTP delivery, the
`pg_cron` branch, and behaviour under `anon`/`authenticated` JWTs issued by
Supabase Auth (Phase 5 covers those with real keys).

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
