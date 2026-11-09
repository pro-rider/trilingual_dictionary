# docs — which file is authoritative

Anything below marked **authoritative** wins over every other document, over
report prose and over chat text. Older documents are kept for history; they are
not deleted, and each carries a superseded banner.

| file | role | authority |
| --- | --- | --- |
| `PHASE2.1-EXECUTION-CONTRACT.md` | how work is done: hard stop, scope, gates, acceptance/rejection | **authoritative** |
| `PHASE2-SCHEMA-CONTRACT.md` | what the schema and resolution contract are (§13 supersedes §1–12 where they disagree) | **authoritative** |
| `ASSET-PINS.json` | the only record of approved shipped-asset hashes | **authoritative** (checked by `backend/tools/check_asset_pin.py`) |
| `ISSUE-REGISTER.md` | open items only, with severity, gate, evidence | **authoritative** for what remains open |
| `PHASE2.1-FINAL-ACCEPTANCE.md` | the acceptance report, kept as a dated record, latest revision last | historical record |
| `PHASE2.1-CORRECTIONS.md` | Phase 2.1 corrections round | historical, superseded by the acceptance report |
| `PHASE2.1-COUNTS.md` | every count with its unit and SQL | reference, still valid |
| `PHASE1-AUDIT.md`, `G1-USER-DATA.md`, `AGENT-NEPALI.md`, `ROADMAP.md`, `PROJECT-STATUS.md` | earlier phases | historical |
| `PHASE1-SCHEMA.md` | superseded twice | historical, do not cite |

Rules of use:

* a label, a fingerprint or a gate that is not in an authoritative file does not
  exist — write it there first, then implement;
* numbers quoted in chat must come from `PHASE2.1-COUNTS.md`, a test run, or a
  tool output, in that order of preference;
* the issue register is the only place to look for "is this still open?";
* changing a value in `ASSET-PINS.json` is an asset change, not a documentation
  edit.
