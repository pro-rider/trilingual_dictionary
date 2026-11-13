"""Checks that need the real Supabase stack, not a stub.

Run against the local stack started by the Supabase CLI (Docker):

    supabase start
    supabase db reset                      # applies supabase/migrations
    eval "$(supabase status -o env)"       # exports API_URL, ANON_KEY, SERVICE_ROLE_KEY
    python supabase/tests/run_local_stack_checks.py

What this proves (and the migration checks cannot):
  * the real `auth.uid()` and a real user JWT, through GoTrue and PostgREST;
  * row-level security as seen by `anon`, `authenticated` and `service_role`;
  * refresh-token rotation, and what a replayed refresh token actually does.

What it still does not prove: pg_cron scheduling on a hosted plan, e-mail
delivery through Resend, and anything about the paid-plan session time-boxing.
Those stay NOT VERIFIED until a hosted staging project exists.

Env vars (no defaults, nothing is committed):
  SUPABASE_URL               e.g. http://127.0.0.1:54321
  SUPABASE_ANON_KEY
  SUPABASE_SERVICE_ROLE_KEY
Optional, for the pg_cron check:
  SUPABASE_DB_URL            e.g. postgresql://postgres:postgres@127.0.0.1:54322/postgres
"""

from __future__ import annotations

import os
import sys
import time
import uuid

import httpx

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok    {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


def main() -> int:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (base and anon and service):
        print("SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY are required")
        return 2
    if not base.startswith(("http://127.0.0.1", "http://localhost")):
        print("refusing to run against a non-local Supabase URL")
        return 2

    admin_headers = {"apikey": service, "Authorization": f"Bearer {service}"}
    rls_headers = {"apikey": anon, "Authorization": f"Bearer {anon}"}
    tag = uuid.uuid4().hex[:8]

    with httpx.Client(timeout=20.0) as client:
        # --- two real users ------------------------------------------------
        users = []
        for name in ("alice", "bob"):
            email = f"{name}-{tag}@example.com"
            r = client.post(
                f"{base}/auth/v1/admin/users",
                headers=admin_headers,
                json={"email": email, "password": "Correct-horse-9", "email_confirm": True},
            )
            check(f"admin creates {name}", r.status_code < 400, r.text[:200])
            uid = r.json().get("id")
            users.append((name, email, uid))

            # Provider-side profiles row, exactly what register/complete writes.
            r = client.post(
                f"{base}/rest/v1/profiles",
                headers={**admin_headers, "Prefer": "return=minimal"},
                json={
                    "user_id": uid,
                    "email": email,
                    "username": f"{name}{tag}",
                    "status": "active",
                    # `status <> 'active' or activated_at is not null` — the
                    # invariant migration 01 puts in the database.
                    "activated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
            check(f"service role writes {name}'s profile", r.status_code < 400, r.text[:200])

        # --- sign in with a password, get a real JWT ----------------------
        tokens = {}
        for name, email, _uid in users:
            r = client.post(
                f"{base}/auth/v1/token?grant_type=password",
                headers={"apikey": anon},
                json={"email": email, "password": "Correct-horse-9"},
            )
            check(f"{name} signs in", r.status_code == 200, r.text[:200])
            if r.status_code == 200:
                tokens[name] = r.json()

        # --- RLS: anon sees nothing, a user sees only their own row -------
        r = client.get(f"{base}/rest/v1/profiles?select=user_id", headers=rls_headers)
        check(
            "anon key alone cannot read profiles",
            r.status_code >= 400 or r.json() == [],
            f"status={r.status_code} body={r.text[:120]}",
        )

        alice = tokens.get("alice", {})
        if alice.get("access_token"):
            r = client.get(
                f"{base}/rest/v1/profiles?select=user_id",
                headers={"apikey": anon, "Authorization": f"Bearer {alice['access_token']}"},
            )
            body = r.json() if r.status_code < 400 else []
            check(
                "real JWT + auth.uid() sees only its own profile",
                r.status_code < 400 and len(body) == 1 and body[0]["user_id"] == users[0][2],
                f"status={r.status_code} body={r.text[:160]}",
            )
            # The other user's row must not be reachable by id either.
            r = client.get(
                f"{base}/rest/v1/profiles?select=user_id&user_id=eq.{users[1][2]}",
                headers={"apikey": anon, "Authorization": f"Bearer {alice['access_token']}"},
            )
            check(
                "a user cannot read another user's profile by id (IDOR)",
                r.status_code >= 400 or r.json() == [],
                f"status={r.status_code} body={r.text[:160]}",
            )

        # --- refresh rotation and replay ---------------------------------
        if alice.get("refresh_token"):
            first = alice["refresh_token"]
            r1 = client.post(
                f"{base}/auth/v1/token?grant_type=refresh_token",
                headers={"apikey": anon},
                json={"refresh_token": first},
            )
            check("refresh returns a new pair", r1.status_code == 200, r1.text[:160])
            rotated = r1.json().get("refresh_token") if r1.status_code == 200 else None
            check(
                "refresh rotates the refresh token",
                bool(rotated) and rotated != first,
                "the refresh token was not replaced",
            )
            time.sleep(40)             # well outside GoTrue's default reuse grace window
            r2 = client.post(
                f"{base}/auth/v1/token?grant_type=refresh_token",
                headers={"apikey": anon},
                json={"refresh_token": first},
            )
            if r2.status_code >= 400:
                check("a replayed refresh token no longer works", True, r2.text[:160])
            else:
                # Observed on the real GoTrue, not a stub: a replayed refresh
                # token can still be accepted after the grace window. So the
                # "reuse revokes the family" rule is NOT Supabase's — revocation
                # is ours (auth_sessions.revoke_all), which is why A30 keeps the
                # sessions table in FastAPI.
                print(
                    "  note  GoTrue still exchanged a replayed refresh token after 40 s "
                    f"(status={r2.status_code}); refresh-reuse revocation is ours, not its"
                )

        # --- cleanup ------------------------------------------------------
        for _name, _email, uid in users:
            client.delete(f"{base}/auth/v1/admin/users/{uid}", headers=admin_headers)
        r = client.get(f"{base}/rest/v1/profiles?select=user_id", headers=admin_headers)
        check("deleting the users cascades the profiles away", r.json() == [], r.text[:120])

    # --- pg_cron, only when the local stack exposes its database --------
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if db_url:
        try:
            import psycopg

            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute("select extname from pg_extension where extname = 'pg_cron'")
                    has_cron = cur.fetchone() is not None
                    if has_cron:
                        check("local stack has pg_cron", True)
                        cur.execute(
                            "select count(*) from cron.job where command like '%purge_transient_rows%'"
                        )
                        check("purge_transient_rows is scheduled", cur.fetchone()[0] >= 1)
                    else:
                        # The CLI stack ships without pg_cron, so the schedule is
                        # genuinely untested here — a hosted project is required
                        # (HUMAN_TODO 13).
                        print("  note  local stack has no pg_cron: schedule stays NOT VERIFIED")
        except Exception as exc:          # noqa: BLE001 - reported, not swallowed
            check("pg_cron check could run", False, str(exc)[:200])
    else:
        print("  note  SUPABASE_DB_URL not set: pg_cron check skipped")

    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    for name in FAILED:
        print(f"  failed: {name}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
