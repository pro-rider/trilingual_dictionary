"""Fail if a pinned asset changed without an approved pin update.

Local rebuild success is never sufficient to replace a shipped asset: this check
makes an accidental replacement visible instead of silent. It compares the file
bytes of `docs/ASSET-PINS.json` against the files on disk.

A file that is not present is reported as ``absent`` and does not fail — CI
checkouts legitimately have no 96 MB asset. A file that is present but differs
fails with a non-zero exit.

    python tools/check_asset_pin.py
    python tools/check_asset_pin.py --repo-root .
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PIN = os.path.join(os.path.dirname(BACKEND), "docs", "ASSET-PINS.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(pin_path=DEFAULT_PIN, repo_root=None):
    with open(pin_path, encoding="utf-8") as f:
        pins = json.load(f)["pins"]
    root = repo_root or os.path.dirname(os.path.dirname(pin_path))
    results, failures = [], []
    for pin in pins:
        path = os.path.join(root, pin["path"])
        if not os.path.exists(path):
            results.append({"path": pin["path"], "state": "absent"})
            continue
        actual = sha256(path)
        if actual == pin["sha256"]:
            results.append({"path": pin["path"], "state": "unchanged", "sha256": actual})
        else:
            results.append({"path": pin["path"], "state": "CHANGED",
                            "expected": pin["sha256"], "actual": actual})
            failures.append("%s changed: expected %s, found %s"
                            % (pin["path"], pin["sha256"], actual))
    return {"ok": not failures, "pins": results, "failures": failures}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", default=DEFAULT_PIN)
    ap.add_argument("--repo-root")
    args = ap.parse_args(argv)
    report = check(args.pin, args.repo_root)
    print(json.dumps(report, indent=2))
    if not report["ok"]:
        print("a shipped asset changed without an approved pin update", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
