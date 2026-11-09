"""The canonical golden-vector process for the shared Python/Dart contract.

``shared/translation_status_golden.json`` and
``shared/translation_resolution_golden.json`` are the contract: the Dart tests
read the same files. This tool is the only sanctioned way to change them, so a
schema tweak cannot silently diverge the two implementations.

    python tools/check_translation_golden.py            # verify (CI gate)
    python tools/check_translation_golden.py --update   # rewrite expected values

``--update`` recomputes every expectation with the Python implementation. It
prints the diff and refuses to write unless every case still derives a *known*
code, so an accidental rule change is visible in review rather than absorbed.

Exit code 1 when the committed file and the implementation disagree, which is
what CI runs on.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from app.translations import resolve, status  # noqa: E402

SHARED = os.path.join(os.path.dirname(BACKEND), "shared")
STATUS_FILE = os.path.join(SHARED, "translation_status_golden.json")
RESOLUTION_FILE = os.path.join(SHARED, "translation_resolution_golden.json")

KNOWN_CODES = set(status.RULES)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def expected_status(case):
    return status.derive(case["input"])


def expected_resolution(case):
    gov = case.get("governance") or {}
    return resolve.resolve_values(
        dictionary_text=case.get("dictionary"),
        governance=gov,
        has_successor=bool(gov.get("has_successor")),
    )


def cases_of(data):
    """Status vectors are a versioned object; resolution vectors are a bare list."""
    return data["cases"] if isinstance(data, dict) else data


def diff(cases, compute, fields):
    problems = []
    for case in cases_of(cases):
        got = compute(case)
        want = case["expected"]
        if got["code" if "code" in want else "status"] not in KNOWN_CODES:
            problems.append("%s: unknown code %s" % (case["name"], got))
        for field in fields:
            if got[field] != want[field]:
                problems.append("%s.%s: committed %r, implementation %r"
                                % (case["name"], field, want[field], got[field]))
    return problems


def update(data, compute, fields):
    changed = []
    for case in cases_of(data):
        got = compute(case)
        key = "code" if "code" in case["expected"] else "status"
        if got[key] not in KNOWN_CODES:
            raise SystemExit("refusing to write: %s derives an unknown code" % case["name"])
        new = {key: got[key]}
        for field in fields:
            if field in ("code", "status"):
                continue
            new[field] = got[field]
        if new != case["expected"]:
            changed.append((case["name"], case["expected"], new))
            case["expected"] = new
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="rewrite the expected values from the Python implementation")
    args = ap.parse_args(argv)

    status_fields = ("code", "label", "visible", "needs_attribution", "attribution")
    resolution_fields = ("text", "source", "status", "visible", "attribution")

    statuses = load(STATUS_FILE)
    resolutions = load(RESOLUTION_FILE)

    failures = diff(statuses, expected_status, status_fields)
    failures += diff(resolutions, expected_resolution, resolution_fields)

    if args.update:
        changed_a = update(statuses, expected_status, status_fields)
        changed_b = update(resolutions, expected_resolution, resolution_fields)
        for path, data, changed in ((STATUS_FILE, statuses, changed_a),
                                    (RESOLUTION_FILE, resolutions, changed_b)):
            if not changed:
                continue
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            for name, old, new in changed:
                print("%s: %s -> %s" % (name, old, new))
        print("updated %d status and %d resolution expectations"
              % (len(changed_a), len(changed_b)))
        return 0

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        print("golden vectors disagree with the implementation", file=sys.stderr)
        return 1
    print("golden vectors match: %d status cases, %d resolution cases"
          % (len(cases_of(statuses)), len(cases_of(resolutions))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
