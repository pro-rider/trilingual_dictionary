-- Phase 2b: FastAPI-owned sessions (A30).
--
-- Supabase's free plan gives no per-device session listing and no session
-- time-boxing / idle timeout, so the backend keeps this table: one row per
-- signed-in device. The access token alone is not proof of a live session —
-- every authenticated request looks this row up by the device hash and refuses
-- a revoked, idle (7 d) or overtime (30 d) row.
--
-- No raw IP, no refresh token, no e-mail: the key is the app's random install
-- id, and it is stored only as a SHA-256 hash.

create table if not exists public.auth_sessions (
    session_id          text primary key,
    user_id             uuid not null references auth.users (id) on delete cascade,
    family_id           text not null,
    device_hash         text not null,
    device_label        text not null default '',
    created_at          timestamptz not null default now(),
    last_seen           timestamptz not null default now(),
    absolute_expires_at timestamptz not null,
    revoked_at          timestamptz,
    constraint auth_sessions_absolute_chk check (absolute_expires_at > created_at)
);

comment on table public.auth_sessions is
    'One row per signed-in device. Deny-all to clients; service role only.';

create index if not exists auth_sessions_user_idx
    on public.auth_sessions (user_id, created_at desc);

-- At most one live session per device, so a re-login replaces rather than
-- stacks, and "revoke this device" cannot leave a second door open.
create unique index if not exists auth_sessions_active_device_uq
    on public.auth_sessions (user_id, device_hash)
    where revoked_at is null;

alter table public.auth_sessions enable row level security;
revoke all on table public.auth_sessions from public, anon, authenticated;

-- Housekeeping: revoked rows are kept 7 days for the "recently signed out"
-- view, hard-expired ones 30 days past their absolute end.
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

    delete from public.auth_sessions
     where (revoked_at is not null and revoked_at < now() - interval '7 days')
        or absolute_expires_at < now() - interval '30 days';
    get diagnostics affected = row_count;
    removed := removed + affected;

    return removed;
end;
$$;

revoke all on function public.purge_transient_rows() from public, anon, authenticated;
grant execute on function public.purge_transient_rows() to service_role;
