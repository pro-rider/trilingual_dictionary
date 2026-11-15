-- Phase 2 additions: columns the FastAPI flow actually needs.
--
-- 1. `profiles.nepali_enabled` — the language toggle is cached on the device
--    (A26), and the server value is what the device syncs from.
-- 2. `auth_challenges.code_hash` + per-window send counters, so FastAPI can own
--    the code (A25): only the hash is stored, never the digits.
-- 3. `auth_signup_tokens` — the opaque token handed out after a code verifies.
--    Kept in its own table so one address can hold a live challenge and a live
--    signup token at the same time without a uniqueness fight.

alter table public.profiles
    add column if not exists nepali_enabled boolean not null default true;

alter table public.auth_challenges
    add column if not exists code_hash text,
    add column if not exists sends_in_window smallint not null default 0,
    add column if not exists window_started_at timestamptz not null default now();

create unique index if not exists auth_challenges_email_purpose_key
    on public.auth_challenges (email_hash, purpose);

create table if not exists public.auth_signup_tokens (
    token_hash      text        primary key,
    email_hash      text        not null,
    -- The address is kept for the 15 minutes the token lives, because the
    -- identity cannot be created without it. It is purged with the token.
    email           text        not null,
    expires_at      timestamptz not null,
    consumed_at     timestamptz,
    created_at      timestamptz not null default now()
);

create index if not exists auth_signup_tokens_email_idx
    on public.auth_signup_tokens (email_hash, created_at desc);

-- Same posture as every other auth table: RLS on, no policies, no client grants.
alter table public.auth_signup_tokens enable row level security;
revoke all on public.auth_signup_tokens from anon, authenticated;
grant select, insert, update, delete on public.auth_signup_tokens to service_role;

-- Extend the existing transient purge instead of adding another job.
create or replace function public.purge_transient_rows()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    removed integer := 0;
    affected integer := 0;
begin
    delete from public.auth_challenges
     where expires_at < now() - interval '1 day';
    get diagnostics affected = row_count;
    removed := removed + affected;

    delete from public.auth_signup_tokens
     where expires_at < now() - interval '1 day';
    get diagnostics affected = row_count;
    removed := removed + affected;

    return removed;
end;
$$;

revoke all on function public.purge_transient_rows() from public, anon, authenticated;
grant execute on function public.purge_transient_rows() to service_role;
