# PROTOCOL.md — Verification Protocol for Non-Trivial Work

Scope: any task that changes data, produces a number that will be acted on, or
touches more than one file. `AGENTS.md` governs code style and architecture; this
file governs **how a claim becomes acceptable**. When the two disagree about
verification, this file wins. When they disagree about code conventions, `AGENTS.md`
wins.

A "non-trivial task" is: a migration, a bulk update, a schema change, a dataset
build, a claim about counts or coverage, or anything whose result another decision
depends on. Renaming a variable is not non-trivial. Rewriting 77 rows is.

---

## The 9 rules

### Rule 1 — Assumption declaration

Before the first write, state the assumptions the plan depends on and how each one
will be falsified. An unlisted assumption that turns out false is a defect, not bad
luck.

*Minimum format* (in the plan or the run-log, not in your head):

| Assumption | How it is checked | Result |
|---|---|---|
| `dictionary.sqlite` still matches the pin | `python tools/preflight.py` | pins match / CHANGED |

**Violation looks like**: "the file exists, so I edited rows in it" without a check.

### Rule 2 — Minimum-change acceptance

Declare the exact change set **before** running, then prove that only that set
changed. "Exit code 0" is not acceptance.

```
intended: 65 rows in images.thumb_path WHERE thumb_path LIKE 'C:%'
actual:   65 rows changed, 0 rows outside the filter
proof:    SELECT of the ids before/after, diffed
```

**Violation looks like**: the 77-row rewrite where only 65 rows were broken.

### Rule 3 — Negative control required

Any check that can pass without proving anything must be run next to a case that
is expected to fail. The failure is the proof.

Two shapes are already in the repo and can be copied:

- `backend/tests/test_execution_guards.py::test_asset_pin_check_fails_on_a_changed_asset`
  — modifies a copy, requires the guard to reject it.
- `backend/tools/check_encoding.py --selftest` — builds corrupted text, requires
  every detector to fire.

**Violation looks like**: "the validator reported no problems" from a validator that
was never seen rejecting anything.

### Rule 4 — Evidence before confidence

A number that will be acted on must be reproducible by a recorded command, with the
command and its output in the report. If the only source is memory or a summary
(including a compacted context), re-derive it or label it `ESTIMATE`.

**Violation looks like**: "the database has about 3,245 Nepali glosses" quoted from
an earlier message rather than from a query run now.

### Rule 5 — Artefact re-read after compaction

After context compaction, or when any doubt exists about an earlier result, re-read
the artefact on disk before continuing. Conversation memory is not evidence.

Numbers and decisions that matter are written to disk **with the input hash** as
they are produced, so re-reading is cheap and the provenance survives.

**Violation looks like**: continuing a migration from remembered row counts.

### Rule 6 — Stop at human gates

Never self-authorize: publishing Nepali glosses or images, changing protected assets,
re-pinning, rewriting production data, or anything the task said needs approval.
Prepare everything, then stop and name the exact decision needed.

The states already defined in `docs/AGENT-NEPALI.md` are the vocabulary:
`proposed → verified → approved | rejected | quarantined`, plus `needs_human`.
Machine output stays a candidate until a reviewer is recorded.

### Rule 7 — Label everything by source

Every important statement carries one of: `FACT` (command + output + file/artifact
id + hash), `INFERENCE` (which facts it rests on), `ESTIMATE` (what it is derived
from), `UNKNOWN` (what evidence would settle it). Do not write all four in the same
confident voice.

### Rule 8 — Git + backup gate before mutation

No migration or bulk script runs unless:

1. `git status --untracked-files=no` is clean (or the dirty paths are named and
   accepted for a read-only run),
2. the pinned assets still match `docs/ASSET-PINS.json`,
3. a backup of the target exists and its SHA-256 is recorded.

Mechanical form:

```powershell
cd backend
.venv\Scripts\python.exe tools\preflight.py `
  --intent "rewrite 65 image paths in copies" `
  --backup "%TEMP%\dictionary-before.sqlite"
```

`PROCEED` is required before the write; `STOP` names which check failed.

### Rule 9 — Encoding integrity + structured run-log

Before any bulk write that touches Nepali/Devanagari (or any non-ASCII column):

```powershell
.venv\Scripts\python.exe tools\check_encoding.py --db data\build\dictionary.sqlite
```

Exit 1 means: do not write. U+FFFD, mojibake sequences that contain no U+FFFD at
all, NUL bytes and control characters are all reported per table/column/row.

Every important script emits one run-log in the same shape, so history is
comparable without re-reading prose:

```json
{
  "run_id": "2026-11-10T15:12:44Z-preflight",
  "script": "preflight.py",
  "intent": "rewrite 65 image paths",
  "declared_change_set": {"table": "images", "filter": "thumb_path LIKE 'C:%'", "rows": 65},
  "actual_changes": {"rows": 65},
  "negative_control": {"name": "corrupt copy", "expected": "reject", "observed": "reject"},
  "inputs": [{"path": "backend/data/build/dictionary.sqlite", "sha256": "…"}],
  "artifacts": ["docs/…json"],
  "exit_code": 0,
  "finished_at": "2026-11-10T15:12:51Z"
}
```

---

## Enforcement map — what is already mechanical

This protocol is not aspirational. Five of its nine rules already have a gate; the
table records where, so the same rule is not implemented twice with two truths.

| Rule | Mechanical today | Where |
|---|---|---|
| 2 — min-change | gate scripts must exit non-zero, never `assert` | `backend/tests/test_execution_guards.py` |
| 3 — negative control | pin guard test rejects a modified copy; encoding self-test rejects corrupt text | `test_asset_pin_check_fails_on_a_changed_asset`, `check_encoding.py --selftest` |
| 4 — evidence | CI re-runs both suites on every push | `.github/workflows/contracts.yml` |
| 7 — labels | required by `AGENTS.md` §8 reporting format | `AGENTS.md` |
| 8 — git + backup | `tools/preflight.py` (new) | exit 1 on dirty tree, changed pin, missing backup |
| 9 — encoding + run-log | `tools/check_encoding.py` (new) | exit 1 on U+FFFD / mojibake / NUL |

## Not yet mechanical

| Rule | Status | What would make it mechanical |
|---|---|---|
| 1 — assumptions | convention only | a required `assumptions` key in the run-log |
| 5 — artefact re-read | convention only | a facts file written with input hashes at run time |
| 6 — human gates | states exist in the database, no queue UI | review queue file with `needs_human` rows |
| 9 — run-log uniformity | two tools emit it; older scripts do not | adopt the schema per script as each is touched |

## Pre-flight checklist (copy into the task report)

```
[ ] intent written in one line
[ ] assumptions listed with a falsification check each
[ ] preflight: PROCEED (git clean, pins match, backup hash recorded)
[ ] encoding gate: ok (when text columns are touched)
[ ] declared change set (table/filter/expected row count)
[ ] negative control named and expected to fail
[ ] rollback path written down
```

## Definition of done

1. The intended change set, and only it, changed — proven by query or hash.
2. The negative control failed as expected.
3. `flutter analyze` clean, `flutter test` green, `pytest -q` green.
4. The run-log exists and names the inputs by hash.
5. Anything not verified is listed as `UNKNOWN`, not implied as fine.
