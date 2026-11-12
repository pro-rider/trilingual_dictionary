"""Pre-flight gate before any migration or bulk write.

Three things the execution contract states but nothing enforced before running a
destructive script:

1. the working tree is clean (or the caller explicitly accepts the risk), so a
   failed run can be reverted with `git restore`;
2. the pinned assets still match `docs/ASSET-PINS.json`, so the thing being
   migrated is the thing that was approved;
3. a backup of the target exists and has a recorded hash, so "rollback" is a
   path, not a wish.

Read-only. Runs `git status`, hashes local files, and prints a JSON run-log.
Exits non-zero when a check fails (`PROTOCOL.md` rules 2, 3, 8).

Usage:
    python tools/preflight.py --intent "rewrite 65 image paths"
    python tools/preflight.py --intent "migrate copies" --backup data/build/dictionary.sqlite
    python tools/preflight.py --allow-dirty --intent "read-only audit"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


GIT_FALLBACKS = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


def _git_exe() -> str:
    """Return a usable git path.

    Windows can have Git installed while the process PATH lacks it. Resolving
    the executable here keeps 'git missing' from being mistaken for 'tree
    clean', which would silently turn this gate into a pass-through.
    """
    found = shutil.which("git")
    if found:
        return found
    for candidate in GIT_FALLBACKS:
        if os.path.exists(candidate):
            return candidate
    return "git"


def _git(repo: Path, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [_git_exe(), *args], cwd=str(repo), capture_output=True,
            text=True, encoding="utf-8", errors="strict", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 2, "git unavailable: %s" % exc
    # Do not strip the whole output: porcelain lines begin with a status
    # column that may be a space (" M path"), and stripping it shifts every
    # path one character left.
    return result.returncode, (result.stdout or "").rstrip("\r\n")


def tracked_changes(repo: Path) -> tuple[bool, list[str], str]:
    """Return (available, changed_paths, detail). Untracked files do not count."""
    code, out = _git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0 or "true" not in out:
        return False, [], "not a git work tree (%s)" % (out.strip() or "git failed")
    code, out = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if code != 0:
        return False, [], "git status failed: %s" % out.strip()
    paths = []
    for line in out.splitlines():
        if not line.strip():
            continue
        # Format is "XY path": the first two columns are status, the third is
        # always a space, so a path can contain leading spaces only if quoted.
        entry = line[3:] if len(line) > 3 else ""
        if " -> " in entry:  # renames report "old -> new"
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.strip().strip('"'))
    return True, paths, ""


def pin_report() -> dict:
    """Reuse the existing pin guard instead of writing a second authority."""
    tools = Path(__file__).resolve().parent
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import check_asset_pin  # noqa: WPS433 (local tool import)
    except Exception as exc:  # pragma: no cover - reported, not hidden
        return {"ok": False, "detail": "cannot import check_asset_pin: %s" % exc}
    try:
        report = check_asset_pin.check()
    except Exception as exc:
        return {"ok": False, "detail": "check_asset_pin raised: %s" % exc}
    states = {p.get("path"): p.get("state") for p in report.get("pins", [])}
    return {"ok": bool(report.get("ok")), "states": states,
            "failures": report.get("failures", [])}


def evaluate(*, repo: Path = REPO, intent: str, allow_dirty: bool = False,
             backup: Path | None = None, skip_pins: bool = False) -> dict:
    """Pure enough to test: every input is a parameter."""
    checks: list[dict] = []

    available, changed, detail = tracked_changes(repo)
    # Unavailable git is an unknown state, not a clean one. Only an explicit
    # --allow-dirty may proceed without proof.
    clean_ok = (not changed) if available else False
    checks.append({
        "name": "git_clean",
        "ok": clean_ok or allow_dirty,
        "detail": detail or ("%d tracked path(s) modified" % len(changed)),
        "paths": changed[:20],
        "overridden": allow_dirty,
    })

    if skip_pins:
        checks.append({"name": "asset_pins", "ok": True, "detail": "skipped by caller"})
    else:
        report = pin_report()
        checks.append({"name": "asset_pins", "ok": report.get("ok", False),
                        "detail": report.get("failures") or report.get("detail") or "pins match",
                        "states": report.get("states", {})})

    if backup is None:
        checks.append({"name": "backup", "ok": True,
                       "detail": "not required for this run (no --backup passed)"})
    else:
        exists = backup.exists() and backup.is_file()
        checks.append({
            "name": "backup",
            "ok": exists and backup.stat().st_size > 0,
            "detail": ("absent: %s" % backup) if not exists else "ok",
            "path": str(backup),
            "bytes": backup.stat().st_size if exists else 0,
            "sha256": sha256_file(backup) if exists else None,
        })

    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "intent": intent,
        "checks": checks,
        "verdict": "PROCEED" if ok else "STOP",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--intent", required=True,
                        help="one line: the exact change set this run will make")
    parser.add_argument("--backup", type=Path,
                        help="file that must exist as the restore source")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="accept a dirty tree (read-only work only)")
    parser.add_argument("--skip-pins", action="store_true",
                        help="only for repos/CI without the build database present")
    parser.add_argument("--json", type=Path, help="also write the run-log here")
    parser.add_argument("--repo", type=Path, default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    report = evaluate(repo=args.repo, intent=args.intent,
                      allow_dirty=args.allow_dirty, backup=args.backup,
                      skip_pins=args.skip_pins)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
    print(text)
    if not report["ok"]:
        failed = [c["name"] for c in report["checks"] if not c["ok"]]
        print("PREFLIGHT: STOP (%s)" % ", ".join(failed), file=sys.stderr)
        return 1
    print("PREFLIGHT: PROCEED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
