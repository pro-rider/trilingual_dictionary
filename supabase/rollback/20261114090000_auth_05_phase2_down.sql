-- Rollback for 20261114090000_auth_05_phase2.sql
--
-- Restores `purge_transient_rows` to its migration-03 behaviour (challenges
-- only) before the columns it now deletes from are removed, then drops the
-- table and columns this migration added.

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
    return removed;
end;
$$;

revoke all on function public.purge_transient_rows() from public, anon, authenticated;
grant execute on function public.purge_transient_rows() to service_role;

drop table if exists public.auth_signup_tokens;

drop index if exists public.auth_challenges_email_purpose_key;

alter table public.auth_challenges
    drop column if exists code_hash,
    drop column if exists sends_in_window,
    drop column if exists window_started_at;

alter table public.profiles
    drop column if exists nepali_enabled;
