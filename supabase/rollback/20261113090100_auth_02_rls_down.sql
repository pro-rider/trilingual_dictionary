-- Rollback for 20261113090100_auth_02_rls.sql
-- Policies are dropped with their table, but dropping the policy explicitly
-- first means a half-applied rollback never leaves RLS on with no reader.

drop policy if exists profiles_select_own on public.profiles;

alter table if exists public.profiles            disable row level security;
alter table if exists public.auth_challenges      disable row level security;
alter table if exists public.auth_rate_limits     disable row level security;
alter table if exists public.auth_lockouts        disable row level security;
alter table if exists public.security_events      disable row level security;
alter table if exists public.blocklist            disable row level security;
alter table if exists public.security_proposals   disable row level security;
alter table if exists public.reserved_usernames   disable row level security;
