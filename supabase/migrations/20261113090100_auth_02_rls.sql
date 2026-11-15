-- ============================================================================
-- Auth system — migration 2 of 4: Row Level Security and grants.
--
-- Two classes of table:
--   1. profiles — clients may read their own row and nothing else. Every write
--      (activate, lockout, locale) happens server-side with the service role.
--   2. everything else — deny-all for anon and authenticated; service role only.
--
-- Grants are written explicitly rather than inherited from Supabase defaults,
-- so a table added here can never end up readable by anon because of a default
-- privilege set we did not look at.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- profiles: own-row read only.
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;

drop policy if exists profiles_select_own on public.profiles;
create policy profiles_select_own
    on public.profiles
    for select
    to authenticated
    using ((select auth.uid()) = user_id);

-- No INSERT / UPDATE / DELETE policy exists on purpose: with RLS on and no
-- policy for a command, that command is refused for anon and authenticated.

revoke all on public.profiles from anon, authenticated;
grant select on public.profiles to authenticated;
grant all on public.profiles to service_role;

-- ---------------------------------------------------------------------------
-- Internal tables: RLS on, no policies at all, no client grants.
-- ---------------------------------------------------------------------------
alter table public.auth_challenges      enable row level security;
alter table public.auth_rate_limits     enable row level security;
alter table public.auth_lockouts        enable row level security;
alter table public.security_events      enable row level security;
alter table public.blocklist            enable row level security;
alter table public.security_proposals   enable row level security;
alter table public.reserved_usernames   enable row level security;

revoke all on public.auth_challenges      from anon, authenticated;
revoke all on public.auth_rate_limits     from anon, authenticated;
revoke all on public.auth_lockouts        from anon, authenticated;
revoke all on public.security_events      from anon, authenticated;
revoke all on public.blocklist            from anon, authenticated;
revoke all on public.security_proposals   from anon, authenticated;
revoke all on public.reserved_usernames   from anon, authenticated;

grant all on public.auth_challenges      to service_role;
grant all on public.auth_rate_limits     to service_role;
grant all on public.auth_lockouts        to service_role;
grant all on public.security_events      to service_role;
grant all on public.blocklist            to service_role;
grant all on public.security_proposals   to service_role;
grant all on public.reserved_usernames   to service_role;

-- Identity columns own sequences; the service role needs them for inserts.
grant usage, select on all sequences in schema public to service_role;

-- ---------------------------------------------------------------------------
-- Self-check: a policy on a deny-all table would silently open it. This query
-- returns zero rows when the migration is correct; run it as a test in Phase 5.
--
--   select tablename, policyname
--     from pg_policies
--    where schemaname = 'public'
--      and tablename in ('auth_challenges','auth_rate_limits','auth_lockouts',
--                        'security_events','blocklist','security_proposals',
--                        'reserved_usernames');
-- ---------------------------------------------------------------------------
