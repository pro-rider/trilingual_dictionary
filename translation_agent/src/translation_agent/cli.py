"""Command line entry point.

Every command takes an explicit ledger path.  There is no code path that
resolves to a production database, and none that imports to production.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit.retention import apply_retention, plan_retention
from .config import AgentConfig, manifest_coverage
from .domain.models import SenseRef
from .export.candidate_export import export_approved
from .generation.pipeline import TranslationPipeline, describe
from .ledger.sqlite_ledger import SqliteLedger
from .providers.fake_provider import FakeProvider


DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "senses" / "pilot_fixture.json"


def _load_senses(path: str) -> list[SenseRef]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        SenseRef(
            sense_key=item["sense_key"],
            entry_id=int(item.get("entry_id", 0)),
            simplified=item.get("simplified", ""),
            pinyin=item.get("pinyin", ""),
            gloss_en=item.get("gloss_en", ""),
        )
        for item in data["senses"]
    ]


def cmd_init(args: argparse.Namespace) -> int:
    with SqliteLedger(args.db) as ledger:
        meta = ledger.verify_schema()
        print(json.dumps({"db": ledger.path, "meta": meta}, ensure_ascii=False, indent=2))
    return 0


def cmd_run_fake(args: argparse.Namespace) -> int:
    senses = _load_senses(args.senses)
    if args.count is not None:
        senses = senses[: args.count]
    config = AgentConfig(ledger_path=args.db).validate()
    provider = FakeProvider()
    with SqliteLedger(args.db) as ledger:
        pipeline = TranslationPipeline(ledger, provider, config)
        result = pipeline.run_batch(senses, batch_id=args.batch, variant_key=args.variant)
        print(describe(result))
        print(
            json.dumps(
                {
                    "ledger_candidates": ledger.count_candidates(),
                    "ledger_requests": ledger.count_requests(),
                },
                indent=2,
            )
        )
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    print(json.dumps(manifest_coverage(args.manifest), ensure_ascii=False, indent=2))
    return 0


def cmd_retention(args: argparse.Namespace) -> int:
    with SqliteLedger(args.db, create=False, protected_manifest=args.manifest) as ledger:
        if args.apply:
            report = apply_retention(ledger)
        else:
            report = plan_retention(ledger)
    report["applied"] = bool(args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with SqliteLedger(args.db, create=False) as ledger:
        states = {}
        for row in ledger.iter_candidates():
            states[row["state"]] = states.get(row["state"], 0) + 1
        print(
            json.dumps(
                {
                    "db": ledger.path,
                    "candidates": ledger.count_candidates(),
                    "requests": ledger.count_requests(),
                    "by_state": states,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    with SqliteLedger(args.db, create=False) as ledger:
        payload = export_approved(ledger, args.out)
        print(
            json.dumps(
                {
                    "out": args.out,
                    "candidates": payload["candidate_count"],
                    "export_checksum": payload["export_checksum"],
                },
                indent=2,
            )
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="translation_agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create or verify the candidate ledger")
    p_init.add_argument("--db", required=True)
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run-fake", help="run a deterministic batch with the fake provider")
    p_run.add_argument("--db", required=True)
    p_run.add_argument("--batch", required=True)
    p_run.add_argument("--senses", default=str(DEFAULT_FIXTURE))
    p_run.add_argument("--count", type=int, default=None)
    p_run.add_argument("--variant", default=None, help="intentional second generation for the same sense")
    p_run.set_defaults(func=cmd_run_fake)

    p_guard = sub.add_parser("guard", help="report which production protections are active")
    p_guard.add_argument("--manifest", default=None)
    p_guard.set_defaults(func=cmd_guard)

    p_retention = sub.add_parser("retention", help="plan or apply raw-response retention")
    p_retention.add_argument("--db", required=True)
    p_retention.add_argument("--manifest", default=None)
    p_retention.add_argument("--apply", action="store_true", help="erase expired payloads (default: plan only)")
    p_retention.set_defaults(func=cmd_retention)

    p_status = sub.add_parser("status", help="summarise the ledger")
    p_status.add_argument("--db", required=True)
    p_status.set_defaults(func=cmd_status)

    p_export = sub.add_parser("export", help="export approved candidates")
    p_export.add_argument("--db", required=True)
    p_export.add_argument("--out", required=True)
    p_export.set_defaults(func=cmd_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:  # e.g. output piped into `head`
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary, fail loudly with non-zero
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
