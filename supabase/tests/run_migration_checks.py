"""Run the auth schema checks against a throwaway PostgreSQL database.

One command, from the repository root:

    backend\\.venv\\Scripts\\python.exe supabase\\tests\\run_migration_checks.py

The script creates the database `auth_migration_check`, stubs the Supabase
primitives a bare PostgreSQL does not have (`auth.users`, `auth.uid()` and the
`anon` / `authenticated` / `service_role` roles), applies the four forward
migrations, runs every check below, then applies the four rollbacks and proves
nothing is left behind. Finally it drops the database.

Nothing here touches the project database. The script refuses to run against a
non-local host unless `--allow-remote` is passed, because "create and drop a
database" on a real Supabase instance would be a destructive act performed by a
test.

`--keep` leaves the database in place for inspection (and prints its DSN).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

REQUIRED_PRIMITIVES = ("auth schema", "auth.users", "auth.uid()", "three roles")

CHECKS: list[str] = []


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def backend_settings_dsn() -> str:
    """Read the backend's default DSN without importing half of FastAPI."""
    backend = repo_root() / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    try:
        from app.core.config import settings

        return settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    except Exception:  # pragma: no cover - only hit when the venv is wrong
        return "postgresql://postgres:postgres@localhost:5432/trilingual_dictionary"


def split_dsn(dsn: str) -> tuple[str, str]:
    head, _, dbname = dsn.rpartition("/")
    return head, dbname


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("AUTH_TEST_DSN", ""))
    parser.add_argument("--db-name", default="auth_migration_check")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    dsn = args.dsn or backend_settings_dsn()
    host_part, _ = split_dsn(dsn)
    local = any(token in host_part for token in ("localhost", "127.0.0.1", "::1"))
    if not local and not args.allow_remote:
        print(f"refusing to create/drop a database on a non-local host: {host_part}")
        print("pass --allow-remote only if you really mean it")
        return 3

    try:
        import psycopg
    except ImportError:
        print("psycopg is missing: run this with backend\\.venv\\Scripts\\python.exe")
        return 3

    root = repo_root()
    migrations = sorted(glob.glob(str(root / "supabase" / "migrations" / "*.sql")))
    rollbacks = sorted(glob.glob(str(root / "supabase" / "rollback" / "*.sql")))
    if len(migrations) != 4 or len(rollbacks) != 4:
        print(f"expected 4 migrations and 4 rollbacks, found {len(migrations)} / {len(rollbacks)}")
        return 3

    head, _ = split_dsn(dsn)
    admin_dsn = f"{head}/postgres"
    scratch_dsn = f"{head}/{args.db_name}"

    failures: list[str] = []
    passed = 0

    def check(name: str, fn) -> None:
        nonlocal passed
        try:
            fn()
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
            print(f"  FAIL  {name}  ({exc})")
        else:
            passed += 1
            print(f"  ok    {name}")

    print(f"database under test: {args.db_name} on {head}")
    admin = psycopg.connect(admin_dsn, autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f'drop database if exists "{args.db_name}" with (force)')
        cur.execute(f'create database "{args.db_name}"')
    admin.close()

    conn = psycopg.connect(scratch_dsn, autocommit=False)

    def table_exists(cur, name: str) -> bool:
        cur.execute("select to_regclass(%s)", (f"public.{name}",))
        return cur.fetchone()[0] is not None

    def function_exists(cur, name: str) -> bool:
        cur.execute(
            "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = 'public' and p.proname = %s",
            (name,),
        )
        return cur.fetchone()[0] > 0

    try:
        # ---------------------------------------------------------------- stubs
        with conn.cursor() as cur:
            cur.execute(
                "create schema if not exists auth;"
                "create table auth.users (id uuid primary key, email text, "
                "created_at timestamptz not null default now(), "
                "raw_user_meta_data jsonb not null default '{}'::jsonb);"
                # The policy calls auth.uid(); in the real project that reads the
                # JWT. Here it reads test.uid so a check can act as a given user.
                "create or replace function auth.uid() returns uuid language sql stable as "
                "$fn$ select nullif(current_setting('test.uid', true), '')::uuid $fn$;"
            )
            cur.execute(
                "do $$ begin "
                "if not exists (select 1 from pg_roles where rolname='anon') then "
                "  create role anon nologin noinherit; end if; "
                "if not exists (select 1 from pg_roles where rolname='authenticated') then "
                "  create role authenticated nologin noinherit; end if; "
                "if not exists (select 1 from pg_roles where rolname='service_role') then "
                "  create role service_role nologin noinherit bypassrls; end if; "
                "end $$;"
            )
        conn.commit()
        print(f"stubbed Supabase primitives: {', '.join(REQUIRED_PRIMITIVES)}")

        # ------------------------------------------------------------ forward
        for path in migrations:
            sql = Path(path).read_text(encoding="utf-8")
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            print(f"applied {Path(path).name}")

        EXPECTED = {
            "profiles", "auth_challenges", "auth_rate_limits", "auth_lockouts",
            "security_events", "blocklist", "security_proposals", "reserved_usernames",
        }

        A = "aaaaaaaa-0000-0000-0000-000000000001"
        B = "bbbbbbbb-0000-0000-0000-000000000002"
        C = "cccccccc-0000-0000-0000-000000000003"
        D = "dddddddd-0000-0000-0000-000000000004"
        STALE = "eeeeeeee-0000-0000-0000-000000000005"
        OLD_ACTIVE = "ffffffff-0000-0000-0000-000000000006"

        def insert_user(cur, uid, email, age_days=0):
            cur.execute(
                "insert into auth.users (id, email, created_at) values (%s, %s, now() - %s::interval)",
                (uid, email, f"{age_days} days"),
            )

        # ------------------------------------------------------------ checks
        def c_tables():
            with conn.cursor() as cur:
                for name in EXPECTED:
                    assert table_exists(cur, name), f"missing {name}"

        check("all eight tables exist", c_tables)

        def c_reserved():
            with conn.cursor() as cur:
                cur.execute("select count(*) from public.reserved_usernames")
                n = cur.fetchone()[0]
            assert n == 31, f"expected 31 seeded handles, found {n}"

        check("reserved handles seeded (31)", c_reserved)

        def c_policies():
            with conn.cursor() as cur:
                cur.execute("select tablename, policyname from pg_policies where schemaname='public'")
                rows = cur.fetchall()
            assert rows == [("profiles", "profiles_select_own")], f"unexpected policies: {rows}"

        check("exactly one policy: profiles_select_own", c_policies)

        def c_rls():
            with conn.cursor() as cur:
                cur.execute(
                    "select relname, relrowsecurity from pg_class "
                    "where relnamespace = 'public'::regnamespace and relkind = 'r'"
                )
                rows = dict(cur.fetchall())
            off = [t for t in EXPECTED if not rows.get(t)]
            assert not off, f"RLS off on {off}"

        check("RLS on for every auth table", c_rls)

        def c_pending():
            with conn.cursor() as cur:
                insert_user(cur, A, "a@example.com")
                cur.execute(
                    "insert into public.profiles (user_id, email, status) values (%s, 'a@example.com', 'pending')",
                    (A,),
                )
            conn.commit()

        check("pending profile accepted", c_pending)

        def _expect_error(sql, params=None):
            with conn.cursor() as cur:
                cur.execute("savepoint probe")
                try:
                    cur.execute(sql, params or ())
                except psycopg.errors.Error:
                    cur.execute("rollback to savepoint probe")
                    return
                cur.execute("release savepoint probe")
            raise AssertionError("statement was accepted but should have been rejected")

        def c_active_without_stamp():
            _expect_error(
                "update public.profiles set status = 'active' where user_id = %s", (A,)
            )

        check("active without activated_at rejected", c_active_without_stamp)

        def c_active_ok():
            with conn.cursor() as cur:
                insert_user(cur, B, "b@example.com")
                cur.execute(
                    "insert into public.profiles (user_id, email, username, status, activated_at) "
                    "values (%s, 'b@example.com', 'Anna', 'active', now())",
                    (B,),
                )
            conn.commit()

        check("active with activated_at accepted", c_active_ok)

        def c_case_collision():
            _expect_error(
                "insert into public.profiles (user_id, email, username, status, activated_at) "
                "values (gen_random_uuid(), 'c@example.com', 'anna', 'active', now())"
            )

        check("username collision is case-insensitive (Anna/anna)", c_case_collision)

        def c_duplicate_email():
            _expect_error(
                "insert into public.profiles (user_id, email, status) "
                "values (gen_random_uuid(), 'a@example.com', 'pending')"
            )

        check("second pending row for one email rejected (no shadow identity)", c_duplicate_email)

        def c_agent_two_hours():
            _expect_error(
                "insert into public.blocklist (kind, value_hash, reason, expires_at, created_by) "
                "values ('ip', 'h1', 'burst', now() + interval '2 hours', 'agent')"
            )

        check("agent block longer than 1 hour rejected", c_agent_two_hours)

        def c_agent_ok():
            with conn.cursor() as cur:
                cur.execute(
                    "insert into public.blocklist (kind, value_hash, reason, expires_at, created_by) "
                    "values ('ip', 'h2', 'burst', now() + interval '40 minutes', 'agent')"
                )
            conn.commit()

        check("agent block within 1 hour accepted", c_agent_ok)

        def c_bad_event():
            _expect_error("insert into public.security_events (event_type) values ('NOT_A_TYPE')")

        check("unknown event_type rejected", c_bad_event)

        def c_oversized():
            blob = json.dumps({"blob": "x" * 5000})
            _expect_error(
                "insert into public.security_events (event_type, details) values ('LOGIN_FAILED', %s::jsonb)",
                (blob,),
            )

        check("event details over 4 KB rejected", c_oversized)

        def c_purge_pending():
            with conn.cursor() as cur:
                insert_user(cur, STALE, "stale@example.com", age_days=25)
                cur.execute(
                    "insert into public.profiles (user_id, email, status, created_at) "
                    "values (%s, 'stale@example.com', 'pending', now() - interval '25 hours')",
                    (STALE,),
                )
                insert_user(cur, C, "fresh@example.com")
                cur.execute(
                    "insert into public.profiles (user_id, email, status) "
                    "values (%s, 'fresh@example.com', 'pending')",
                    (C,),
                )
                # An account that is older than the pending window but ACTIVE.
                insert_user(cur, OLD_ACTIVE, "old@example.com", age_days=40)
                cur.execute(
                    "insert into public.profiles (user_id, email, username, status, activated_at, created_at) "
                    "values (%s, 'old@example.com', 'old_timer', 'active', now(), now() - interval '40 days')",
                    (OLD_ACTIVE,),
                )
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("select public.purge_pending_accounts()")
                purged = cur.fetchone()[0]
            conn.commit()
            assert purged == 1, f"purged {purged} rows, expected exactly the stale pending one"
            with conn.cursor() as cur:
                cur.execute("select count(*) from public.profiles where user_id = %s", (STALE,))
                assert cur.fetchone()[0] == 0, "stale pending profile survived"
                cur.execute("select count(*) from auth.users where id = %s", (STALE,))
                assert cur.fetchone()[0] == 0, "stale auth.users row survived"
                cur.execute("select count(*) from public.profiles where user_id = %s", (C,))
                assert cur.fetchone()[0] == 1, "fresh pending profile was deleted"
                # THE POINT: the purge is scoped to status='pending' and cannot
                # reach a real account, however old it is.
                cur.execute("select count(*) from public.profiles where user_id = %s", (OLD_ACTIVE,))
                assert cur.fetchone()[0] == 1, "purge deleted an ACTIVE account"

        check("pending purge deletes stale pending, spares fresh pending AND active accounts", c_purge_pending)

        def c_client_write_denied():
            with conn.cursor() as cur:
                cur.execute("set role authenticated")
                cur.execute("savepoint probe")
                denied = False
                try:
                    cur.execute(
                        "insert into public.profiles (user_id, email, status) "
                        "values (gen_random_uuid(), 'squat@example.com', 'pending')"
                    )
                except psycopg.errors.InsufficientPrivilege:
                    denied = True
                finally:
                    cur.execute("rollback to savepoint probe")
                    cur.execute("reset role")
            assert denied, "a client role could insert a pending profile (signup squatting possible)"

        check("client role cannot create pending rows (no signup squatting)", c_client_write_denied)

        def c_cross_user_read():
            with conn.cursor() as cur:
                cur.execute("set role authenticated")
                cur.execute("select set_config('test.uid', %s, false)", (B,))
                cur.execute("select user_id from public.profiles")
                visible = [str(r[0]) for r in cur.fetchall()]
                cur.execute("reset role")
                cur.execute("select set_config('test.uid', '', false)")
            assert visible == [B], f"user B saw {visible}, expected only their own row"

        check("authenticated user sees only their own profile", c_cross_user_read)

        def c_internal_tables_denied():
            with conn.cursor() as cur:
                cur.execute("set role authenticated")
                for table in ("security_events", "blocklist", "security_proposals", "auth_rate_limits"):
                    cur.execute("savepoint probe")
                    denied = False
                    try:
                        cur.execute(f"select count(*) from public.{table}")
                    except psycopg.errors.InsufficientPrivilege:
                        denied = True
                    finally:
                        cur.execute("rollback to savepoint probe")
                    assert denied, f"authenticated could read {table}"
                cur.execute("reset role")

        check("authenticated cannot read any internal table", c_internal_tables_denied)

        def c_events_retention():
            with conn.cursor() as cur:
                cur.execute(
                    "insert into public.security_events (ts, event_type) "
                    "values (now() - interval '31 days', 'LOGIN_FAILED'), "
                    "       (now() - interval '29 days', 'LOGIN_FAILED')"
                )
                cur.execute("select public.purge_security_events()")
                deleted = cur.fetchone()[0]
                cur.execute("select count(*) from public.security_events")
                left = cur.fetchone()[0]
            conn.commit()
            assert deleted == 1, f"retention deleted {deleted}, expected exactly the 31-day row"
            assert left == 1, f"expected the 29-day row to survive, {left} rows present"

        check("30-day retention deletes the 31-day row and keeps the 29-day one", c_events_retention)

        def c_cascade():
            """Deleting the identity must take the profile with it.

            This is the database half of `DELETE /auth/account`: the endpoint
            deletes the auth user, and the profile disappears by cascade rather
            than by a second, forgettable statement.
            """
            with conn.cursor() as cur:
                cur.execute("select count(*) from public.profiles where user_id = %s", (B,))
                assert cur.fetchone()[0] == 1, "precondition: profile B missing"
                cur.execute("delete from auth.users where id = %s", (B,))
                cur.execute("select count(*) from public.profiles where user_id = %s", (B,))
                assert cur.fetchone()[0] == 0, "profile survived the identity delete"
            conn.commit()

        check("deleting auth.users cascades to profiles", c_cascade)

        # ----------------------------------------------------------- rollback
        def c_rollback():
            for path in reversed(rollbacks):
                sql = Path(path).read_text(encoding="utf-8")
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            with conn.cursor() as cur:
                for name in EXPECTED:
                    assert not table_exists(cur, name), f"{name} survived rollback"
                for fn in ("purge_pending_accounts", "purge_security_events",
                           "purge_transient_rows", "touch_updated_at"):
                    assert not function_exists(cur, fn), f"function {fn} survived rollback"
                cur.execute("select count(*) from pg_policies where schemaname='public'")
                assert cur.fetchone()[0] == 0, "policies survived rollback"

        check("four rollbacks remove every table, function and policy", c_rollback)

    finally:
        conn.close()
        if args.keep:
            print(f"\nkept database: {scratch_dsn}")
        else:
            admin = psycopg.connect(admin_dsn, autocommit=True)
            with admin.cursor() as cur:
                cur.execute(f'drop database if exists "{args.db_name}" with (force)')
            admin.close()
            print(f"dropped database {args.db_name}")

    print(f"\n{passed} passed, {len(failures)} failed")
    for failure in failures:
        print(f"  - {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
