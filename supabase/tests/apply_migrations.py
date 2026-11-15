"""Apply the auth migrations to a real PostgreSQL / Supabase project.

This is the companion to ``run_migration_checks.py``. The check script creates a
throwaway database and proves the migrations work; this script applies them for
real, records what it applied, and refuses to touch anything it cannot identify
as the target you named.

One command, from the repository root:

    backend\\.venv\\Scripts\\python.exe supabase\\tests\\apply_migrations.py \
        --dsn "$env:DATABASE_URL" --allow-remote

Behaviour
--------
* Reads every ``supabase/migrations/*.sql`` in filename order.
* Records each applied file in ``public.schema_migrations`` so a second run is a
  no-op instead of a re-apply.
* ``--dry-run`` prints the plan and touches nothing.
* A non-loopback host is refused unless ``--allow-remote`` is passed, so nobody
  applies this to a shared database by accident.

The DSN must use the plain ``postgresql://`` scheme; the backend's
``postgresql+psycopg://`` form is accepted too and stripped here.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - wrong interpreter
    print("psycopg is missing: run this with backend\\.venv\\Scripts\\python.exe", file=sys.stderr)
    raise SystemExit(2)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def migration_files() -> list[Path]:
    return sorted((repo_root() / "supabase" / "migrations").glob("*.sql"))


def normalise(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://").strip()


def host_of(dsn: str) -> str:
    # postgresql://user:pass@host:port/db — the host is between @ and the next : or /
    tail = dsn.split("@")[-1] if "@" in dsn else ""
    for sep in (":", "/"):
        if sep in tail:
            tail = tail.split(sep, 1)[0]
            break
    return tail.lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dsn = normalise(args.dsn)
    if not dsn:
        print("no DSN: pass --dsn or set DATABASE_URL", file=sys.stderr)
        return 2
    host = host_of(dsn)
    if host not in LOCAL_HOSTS and not args.allow_remote:
        print(f"refusing host {host!r}: pass --allow-remote for a real project", file=sys.stderr)
        return 3

    files = migration_files()
    if not files:
        print("no migrations found", file=sys.stderr)
        return 4

    print(f"target host: {host}")
    for f in files:
        print(f"  plan: {f.name}")
    if args.dry_run:
        print("dry run: nothing applied")
        return 0

    applied_now: list[str] = []
    skipped: list[str] = []
    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists public.schema_migrations (
                    version    text primary key,
                    applied_at timestamptz not null default now()
                )
                """
            )
            conn.commit()
            cur.execute("select version from public.schema_migrations")
            already = {row[0] for row in cur.fetchall()}

        for f in files:
            if f.stem in already:
                skipped.append(f.name)
                print(f"  skip: {f.name} (already recorded)")
                continue
            sql = f.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "insert into public.schema_migrations (version) values (%s)", (f.stem,)
                    )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                print(f"FAILED on {f.name}: {exc}", file=sys.stderr)
                print("rolled back this file; earlier files stay applied", file=sys.stderr)
                return 5
            applied_now.append(f.name)
            print(f"  applied: {f.name}")

    print(f"done: {len(applied_now)} applied, {len(skipped)} already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
