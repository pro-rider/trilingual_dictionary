-- ============================================================================
-- Auth system — migration 1 of 4: tables, constraints, indexes, invariants.
--
-- Identity engine is Supabase Auth. This schema stores only what Supabase Auth
-- does not: the username, the pending/active lifecycle, abuse signals and the
-- advisory agent's output. No password, code or token column exists here on
-- purpose — those live in auth.* and never leave it.
--
-- Read together with docs/AUTH-SCHEMA.md. Nothing in this file has been applied
-- to a project yet; see docs/HUMAN_TODO.md for the order of operations.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- profiles — one row per human account. The only table clients may read.
--
-- Invariant that matters: status='active' requires activated_at. Step 3 of the
-- signup flow (username + password chosen) is the only writer that may set it,
-- so an email that stops after verifying the code can never be a usable login.
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
    user_id             uuid primary key references auth.users (id) on delete cascade,
    username            text,
    email               text,
    display_name        text,
    status              text        not null default 'pending',
    locale              text        not null default 'en',
    failed_login_count  integer     not null default 0,
    lockout_until       timestamptz,
    last_login_at       timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    activated_at        timestamptz,
    constraint profiles_status_chk
        check (status in ('pending', 'active', 'disabled', 'deleted')),
    constraint profiles_locale_chk
        check (locale in ('en', 'zh', 'ne')),
    -- Spec: 3-20 chars, a-z 0-9 _ . only. Case is preserved for display; the
    -- unique index below compares lower(username), so "Anna" and "anna" collide.
    constraint profiles_username_chk
        check (username is null or username ~ '^[A-Za-z0-9_.]{3,20}$'),
    -- The "pending is not an account" invariant, enforced in the database.
    constraint profiles_activated_chk
        check (status <> 'active' or activated_at is not null)
);

comment on table  public.profiles is
    'One row per account. Rows are created at email verification (status=pending) and become usable only at status=active.';
comment on column public.profiles.username is
    'Login identifier. Unique case-insensitively. Null while pending.';
comment on column public.profiles.failed_login_count is
    'Consecutive failures feeding the progressive lockout; reset on success.';
comment on column public.profiles.lockout_until is
    'When non-null and in the future, login is refused before any password check.';

-- Case-insensitive username uniqueness (spec: unique index on lower(username)).
create unique index if not exists profiles_username_key
    on public.profiles (lower(username))
    where username is not null;

-- One profile per email address, so a pending signup cannot be duplicated and
-- a second auth.users row for the same address cannot acquire a profile.
create unique index if not exists profiles_email_key
    on public.profiles (lower(email))
    where email is not null;

-- Cleanup job scans (status, created_at); lockout sweeper scans lockout_until.
create index if not exists profiles_status_created_idx
    on public.profiles (status, created_at);
create index if not exists profiles_lockout_idx
    on public.profiles (lockout_until)
    where lockout_until is not null;

-- ---------------------------------------------------------------------------
-- auth_challenges — one row per emailed code, so "max 5 wrong attempts per
-- code" and "resend cooldown" are counted server-side instead of inferred.
-- Email is stored hashed: this table must never become a list of addresses.
-- ---------------------------------------------------------------------------
create table if not exists public.auth_challenges (
    id                  uuid        primary key default gen_random_uuid(),
    purpose             text        not null,
    email_hash          text        not null,
    attempts            smallint    not null default 0,
    max_attempts        smallint    not null default 5,
    code_window_start   timestamptz not null default now(),
    expires_at          timestamptz not null default (now() + interval '10 minutes'),
    consumed_at         timestamptz,
    created_at          timestamptz not null default now(),
    constraint auth_challenges_purpose_chk
        check (purpose in ('signup', 'reset')),
    constraint auth_challenges_max_attempts_chk
        check (max_attempts between 1 and 10),
    constraint auth_challenges_attempts_chk
        check (attempts >= 0)
);

comment on table public.auth_challenges is
    'Per-code attempt budget and resend window. Holds an email hash, never the address.';

create index if not exists auth_challenges_email_idx
    on public.auth_challenges (email_hash, created_at desc);
create index if not exists auth_challenges_open_idx
    on public.auth_challenges (email_hash, purpose)
    where consumed_at is null;

-- ---------------------------------------------------------------------------
-- auth_rate_limits — fixed-window counters in Postgres, because the spec allows
-- either Upstash Redis or a Postgres table and this keeps the stack zero-cost.
-- bucket encodes its own dimension: ip:<hash>, user:<uuid>, device:<id>,
-- email:<hash>, endpoint:<name>.
-- ---------------------------------------------------------------------------
create table if not exists public.auth_rate_limits (
    bucket          text        not null,
    window_start    timestamptz not null,
    hits            integer     not null default 0,
    primary key (bucket, window_start),
    constraint auth_rate_limits_hits_chk check (hits >= 0)
);

comment on table public.auth_rate_limits is
    'Fixed-window request counters, one row per bucket per window. Pruned by cron.';

create index if not exists auth_rate_limits_window_idx
    on public.auth_rate_limits (window_start);

-- Progressive lockout state per subject (account, ip, device).
create table if not exists public.auth_lockouts (
    subject             text        primary key,
    failures            integer     not null default 0,
    first_failure_at    timestamptz not null default now(),
    locked_until        timestamptz,
    updated_at          timestamptz not null default now(),
    constraint auth_lockouts_failures_chk check (failures >= 0)
);

comment on table public.auth_lockouts is
    'Escalating lockout ladder (1 min / 5 min / 15 min) keyed by subject.';

-- ---------------------------------------------------------------------------
-- security_events — append-only audit trail. Details are structured fields
-- only: no passwords, no codes, no tokens, no raw user text (spec).
-- ---------------------------------------------------------------------------
create table if not exists public.security_events (
    id              bigint      generated always as identity primary key,
    ts              timestamptz not null default now(),
    event_type      text        not null,
    severity        smallint    not null default 2,
    ip_hash         text,
    device_id       text,
    user_id         uuid,
    endpoint        text,
    details         jsonb       not null default '{}'::jsonb,
    action_taken    text,
    constraint security_events_type_chk check (event_type in (
        'LOGIN_FAILED', 'LOGIN_SUCCESS', 'LOCKOUT', 'CODE_SENT', 'CODE_BRUTEFORCE',
        'CODE_EXPIRED', 'INJECTION_PATTERN', 'UPLOAD_REJECTED', 'RATE_LIMIT_HIT',
        'TOKEN_REUSE', 'SIGNUP_STARTED', 'SIGNUP_BURST', 'ACCOUNT_ACTIVATED',
        'PASSWORD_RESET', 'LOGOUT_ALL', 'BLOCKLIST_HIT', 'BLOCK_CREATED',
        'PROPOSAL_CREATED', 'PROPOSAL_DECIDED', 'ADMIN_ACTION'
    )),
    constraint security_events_severity_chk check (severity between 1 and 5),
    -- Bounded payload: a log line is an observation, not a data store.
    constraint security_events_details_size_chk check (pg_column_size(details) < 4096)
);

comment on table public.security_events is
    'Append-only security audit trail, service-role only. Retained 30 days.';

create index if not exists security_events_ts_idx
    on public.security_events (ts desc);
create index if not exists security_events_type_ts_idx
    on public.security_events (event_type, ts desc);
create index if not exists security_events_ip_ts_idx
    on public.security_events (ip_hash, ts desc)
    where ip_hash is not null;
create index if not exists security_events_user_ts_idx
    on public.security_events (user_id, ts desc)
    where user_id is not null;
create index if not exists security_events_device_ts_idx
    on public.security_events (device_id, ts desc)
    where device_id is not null;

-- ---------------------------------------------------------------------------
-- blocklist — checked on every auth request. created_by records who decided,
-- and the check constraint hard-caps what the agent may do on its own: an
-- agent-created block cannot outlive one hour, whatever the application says.
-- ---------------------------------------------------------------------------
create table if not exists public.blocklist (
    id              bigint      generated always as identity primary key,
    kind            text        not null,
    value_hash      text        not null,
    reason          text        not null,
    expires_at      timestamptz,
    created_by      text        not null default 'rule',
    created_at      timestamptz not null default now(),
    constraint blocklist_kind_chk
        check (kind in ('ip', 'device', 'email', 'user')),
    constraint blocklist_created_by_chk
        check (created_by in ('rule', 'agent', 'human')),
    constraint blocklist_agent_ttl_chk
        check (
            created_by <> 'agent'
            or (expires_at is not null and expires_at <= created_at + interval '1 hour')
        )
);

comment on table public.blocklist is
    'Active blocks by hashed identifier. An agent block is capped at 1 hour by a check constraint.';

create unique index if not exists blocklist_kind_value_key
    on public.blocklist (kind, value_hash);
create index if not exists blocklist_expiry_idx
    on public.blocklist (expires_at)
    where expires_at is not null;

-- ---------------------------------------------------------------------------
-- security_proposals — the advisory agent's only write target. Evidence holds
-- event ids, never free text lifted from user input.
-- ---------------------------------------------------------------------------
create table if not exists public.security_proposals (
    id                  bigint      generated always as identity primary key,
    created_at          timestamptz not null default now(),
    window_start        timestamptz not null,
    window_end          timestamptz not null,
    summary             text        not null,
    severity            smallint    not null default 2,
    evidence            jsonb       not null default '[]'::jsonb,
    recommended_action  text        not null,
    proposed_block      jsonb,
    status              text        not null default 'proposed',
    decided_by          text,
    decided_at          timestamptz,
    expires_at          timestamptz not null default (now() + interval '72 hours'),
    constraint security_proposals_severity_chk check (severity between 1 and 5),
    constraint security_proposals_status_chk
        check (status in ('proposed', 'approved', 'rejected', 'executed', 'expired')),
    constraint security_proposals_evidence_chk
        check (jsonb_typeof(evidence) = 'array' and pg_column_size(evidence) < 8192),
    constraint security_proposals_window_chk check (window_end >= window_start)
);

comment on table public.security_proposals is
    'Agent output for human review. The agent cannot ban, delete or change passwords; the strongest automatic action is a 1-hour block.';

create index if not exists security_proposals_status_idx
    on public.security_proposals (status, created_at desc);

-- ---------------------------------------------------------------------------
-- reserved_usernames — blocked handles. Seeded in migration 4.
-- ---------------------------------------------------------------------------
create table if not exists public.reserved_usernames (
    name            text        primary key,
    reason          text,
    created_at      timestamptz not null default now()
);

comment on table public.reserved_usernames is
    'Handles nobody may register, compared case-insensitively.';

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists profiles_touch on public.profiles;
create trigger profiles_touch
    before update on public.profiles
    for each row execute function public.touch_updated_at();

drop trigger if exists auth_lockouts_touch on public.auth_lockouts;
create trigger auth_lockouts_touch
    before update on public.auth_lockouts
    for each row execute function public.touch_updated_at();
