-- Rollback for 20261113090200_auth_03_retention.sql
-- Unschedules the cron jobs when pg_cron exists, then drops the three
-- functions. Refusing to fail when pg_cron is missing keeps the rollback
-- runnable on a project where the extension was never enabled.

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
    end if;
end;
$$;

drop function if exists public.purge_transient_rows();
drop function if exists public.purge_security_events();
drop function if exists public.purge_pending_accounts();
