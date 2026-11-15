-- ============================================================================
-- Auth system — migration 3 of 4: retention and scheduled cleanup.
--
-- Three jobs, all idempotent and all safe to run by hand:
--   purge_pending_accounts() — deletes profiles older than 24 h that never
--                              reached step 3, and the auth.users row behind
--                              them, so a half-finished signup leaves nothing.
--   purge_security_events()  — 30-day retention, per the spec and the privacy
--                              policy wording.
--   purge_transient_rows()   — expired challenges, stale rate-limit windows,
--                              expired lockouts and expired blocklist rows.
--
-- pg_cron is scheduled only if the extension is already installed. Supabase
-- enables it from the dashboard (Database → Extensions); the migration must not
-- fail on a project where it is off.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Delete half-finished signups.
--
-- Deleting from auth.users is normally done through the Admin API; the direct
-- delete is used here because it is atomic with the profile row and cascades
-- correctly. It must run as a privileged role (the migration owner), which is
-- why the function is SECURITY DEFINER and revoked from clients.
-- ---------------------------------------------------------------------------
create or replace function public.purge_pending_accounts()
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public, auth
as $$
declare
    deleted integer := 0;
begin
    with stale as (
        select p.user_id
          from public.profiles p
         where p.status = 'pending'
           and p.created_at < now() - interval '24 hours'
    )
    delete from auth.users u
     using stale s
     where u.id = s.user_id;

    get diagnostics deleted = row_count;
    return deleted;
end;
$$;

comment on function public.purge_pending_accounts is
    'Deletes signups that verified an email but never chose a username/password (24 h).';

-- ---------------------------------------------------------------------------
-- 30-day retention for the audit trail.
-- ---------------------------------------------------------------------------
create or replace function public.purge_security_events()
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    deleted integer := 0;
begin
    delete from public.security_events
     where ts < now() - interval '30 days';

    get diagnostics deleted = row_count;
    return deleted;
end;
$$;

comment on function public.purge_security_events is
    'Enforces the documented 30-day retention of security_events.';

-- ---------------------------------------------------------------------------
-- Transient rows: nothing in these tables is meant to live long.
-- ---------------------------------------------------------------------------
create or replace function public.purge_transient_rows()
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
    deleted integer := 0;
begin
    delete from public.auth_challenges
     where created_at < now() - interval '2 days';

    delete from public.auth_rate_limits
     where window_start < now() - interval '2 days';

    delete from public.auth_lockouts
     where failures = 0
       and updated_at < now() - interval '7 days';

    delete from public.auth_lockouts
     where (locked_until is null or locked_until < now() - interval '7 days')
       and updated_at < now() - interval '7 days';

    delete from public.blocklist
     where expires_at is not null
       and expires_at < now() - interval '7 days';

    get diagnostics deleted = row_count;
    return deleted;
end;
$$;

comment on function public.purge_transient_rows is
    'Prunes expired codes, rate-limit windows, settled lockouts and expired blocks.';

-- Only the server may call these.
revoke all on function public.purge_pending_accounts() from anon, authenticated;
revoke all on function public.purge_security_events()  from anon, authenticated;
revoke all on function public.purge_transient_rows()   from anon, authenticated;
grant execute on function public.purge_pending_accounts() to service_role;
grant execute on function public.purge_security_events()  to service_role;
grant execute on function public.purge_transient_rows()   to service_role;

-- ---------------------------------------------------------------------------
-- Schedule (optional). Runs only when pg_cron is present; otherwise the same
-- functions are called by the FastAPI scheduler documented in docs/AUTH-SCHEMA.md.
-- ---------------------------------------------------------------------------
do $$
begin
    if exists (select 1 from pg_extension where extname = 'pg_cron') then
        begin
            perform cron.unschedule('auth-purge-pending');
        exception when others then null;
        end;
        begin
            perform cron.unschedule('auth-purge-events');
        exception when others then null;
        end;
        begin
            perform cron.unschedule('auth-purge-transient');
        exception when others then null;
        end;

        perform cron.schedule(
            'auth-purge-pending', '17 * * * *',
            $cron$select public.purge_pending_accounts();$cron$
        );
        perform cron.schedule(
            'auth-purge-events', '23 3 * * *',
            $cron$select public.purge_security_events();$cron$
        );
        perform cron.schedule(
            'auth-purge-transient', '*/30 * * * *',
            $cron$select public.purge_transient_rows();$cron$
        );

        raise notice 'pg_cron present: auth cleanup jobs scheduled.';
    else
        raise notice 'pg_cron absent: schedule the three purge functions on the FastAPI side.';
    end if;
end;
$$;
