-- Down migration for 20261115090000_auth_06_sessions.sql.
-- Order matters: restore the phase-2 purge function first (so it stops
-- referencing the table), then drop the table.

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

drop table if exists public.auth_sessions;
