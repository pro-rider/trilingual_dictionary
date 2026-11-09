"""Create, back up, migrate or roll back the translation store.

    python backend/tools/migrate_translations.py --dry-run
    python backend/tools/migrate_translations.py --data-version 2026-11-09.3
    python backend/tools/migrate_translations.py --rollback data/build/translations.db.bak-20261109T120000Z
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.translations import schema  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(BACKEND, "data", "build", schema.DB_FILENAME))
    ap.add_argument("--data-version", default=None,
                    help="dictionary version the store is being built against")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", default=None, help="restore from this backup file")
    args = ap.parse_args(argv)

    if args.rollback:
        result = schema.rollback(args.db, args.rollback, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    report = schema.migrate(args.db, dry_run=args.dry_run, data_version=args.data_version)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
