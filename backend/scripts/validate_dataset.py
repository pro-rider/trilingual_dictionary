"""Data-integrity validation (v2 spec).

Fails if any sense is missing one of the three meanings, or if a sense has no
reviewed example. Run: python -m scripts.validate_dataset
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.dataset import load_entries  # noqa: E402


def validate() -> list[str]:
    errors: list[str] = []
    entries = load_entries()
    if not entries:
        return ["dataset is empty"]

    for e in entries:
        eid = e.get("entry_id", "?")
        for s in e.get("senses", []):
            sid = s.get("sense_id", "?")
            for field in ("meaning_en", "meaning_zh", "meaning_ne"):
                if not (s.get(field) or "").strip():
                    errors.append(f"[{eid}] sense {sid} missing {field}")
            reviewed = [
                x
                for x in s.get("examples", [])
                if x.get("review_status") == "approved"
            ]
            if not reviewed:
                errors.append(
                    f"[{eid}] sense {sid} has no reviewed example"
                )
    return errors


if __name__ == "__main__":
    errs = validate()
    if errs:
        for err in errs:
            print("FAIL:", err)
        print(f"{len(errs)} issue(s) found.")
        sys.exit(1)
    print("OK: dataset integrity valid.")
