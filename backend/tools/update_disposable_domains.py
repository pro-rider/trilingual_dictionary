"""Download the maintained disposable-email blocklist.

The list is vendored so the backend never depends on the network at request time
and so a test can assert exactly what is blocked. Re-run this when the upstream
list matters (new domains appear every week):

    backend\\.venv\\Scripts\\python.exe backend\\tools\\update_disposable_domains.py

Upstream: https://github.com/disposable-email-domains/disposable-email-domains
The upstream licence text is saved next to the list as DISPOSABLE-LICENSE.txt;
read it before redistributing.
"""

from __future__ import annotations

from pathlib import Path

import httpx

RAW = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master"
TARGET_DIR = Path(__file__).resolve().parents[1] / "data"


def fetch(name: str, target: Path) -> int:
    response = httpx.get(f"{RAW}/{name}", timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    lines = [line.strip().lower() for line in response.text.splitlines()]
    body = "\n".join(line for line in lines if line and not line.startswith("#"))
    target.write_text(body + "\n", encoding="utf-8", newline="\n")
    return len(body.splitlines())


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    domains = fetch("disposable_email_blocklist.conf", TARGET_DIR / "disposable_email_blocklist.conf")
    TARGET_DIR.joinpath("DISPOSABLE-LICENSE.txt").write_text(
        "Source: https://github.com/disposable-email-domains/disposable-email-domains\n"
        "License reported by the GitHub API for that repository: NOASSERTION (\"Other\").\n"
        "\n"
        "Because no explicit licence is stated, this generated list is treated as a\n"
        "deploy-time artifact: it is git-ignored and never redistributed with this\n"
        "repository. Check the upstream repository yourself before shipping it.\n"
        "The small hand-written floor in data/disposable_email_seed.txt ships instead.\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"domains: {domains}")
    print(f"written: {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
