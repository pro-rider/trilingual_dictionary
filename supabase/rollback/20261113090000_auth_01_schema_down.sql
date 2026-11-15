-- Rollback for 20261113090000_auth_01_schema.sql
-- Removes every object created by the forward migration. Safe to run only
-- after the rollbacks for migrations 2-4 (policy, cron, seed) have run.

drop trigger if exists profiles_touch on public.profiles;
drop trigger if exists auth_lockouts_touch on public.auth_lockouts;

drop table if exists public.security_proposals;
drop table if exists public.blocklist;
drop table if exists public.security_events;
drop table if exists public.auth_lockouts;
drop table if exists public.auth_rate_limits;
drop table if exists public.auth_challenges;
drop table if exists public.reserved_usernames;
drop table if exists public.profiles;

drop function if exists public.touch_updated_at();
