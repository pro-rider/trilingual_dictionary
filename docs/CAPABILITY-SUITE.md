# Capability Suite — a fixed benchmark for the agent, re-run after every significant change

Purpose: make "the agent got better" measurable instead of felt. The prompts below
target the failure modes recorded in the 10 November 2026 review (unexamined
assumptions, vacuous checks, weak recovery, lost-in-the-middle, visual judgement). They
are cheap to run, and each one has a pass condition that a second person could check.

Baseline status: **UNKNOWN** — this suite has not been run yet. Do not quote a score
until a run is recorded in the log.

---

## Run procedure

1. Run the 10 prompts below in a **fresh session** each (no carry-over context).
2. Score each 0–2 with the rubric.
3. Append one line to `docs/CAPABILITY-LOG.jsonl`:

```json
{"run_id":"2026-11-10T15:40:00Z","suite":"capability-v1","scores":{"P1":2,"P2":1,"P3":2,"P4":2,"P5":0,"P6":1,"P7":2,"P8":1,"P9":2,"P10":1},"total":14,"notes":"P5 failed: middle fact missed after 2 turns"}
```

4. Compare with the previous line. A drop of 2 or more points on one prompt is a
   regression to investigate before the next feature work.

## Scoring rubric

| Score | Meaning |
|---|---|
| 2 | Passed, and the evidence is reproducible (command/output or file reference shown) |
| 1 | Passed with a caveat that is stated explicitly (e.g. answered but did not verify) |
| 0 | Failed, or answered confidently without evidence |

A run is **invalid** if any prompt was scored from memory of a previous run rather
than from this run's output.

---

## The 10 prompts

| ID | Prompt (short form) | What it tests | Pass condition |
|---|---|---|---|
| P1 | "Add a count of rows matching a filter to an existing script, then prove the change did not touch anything else." | minimum change + negative control | declares the change set, shows a before/after diff, and a negative case that fails |
| P2 | "How many rows in this database have a Devanagari gloss that also contains Latin letters?" | assumption handling | runs a query and cites the command; does not answer from memory; says `UNKNOWN` if the DB is absent |
| P3 | Ask the same factual question three ways (direct, paraphrased, nested in a task). | consistency | all three answers agree, or the difference is explained |
| P4 | "Return this result as JSON matching this schema. If you cannot, say why." | structured output | valid JSON or an explicit refusal with the reason; never invalid JSON |
| P5 | A long distractor text with one fact at ~50%, then two unrelated turns, then "what was the passphrase?" | lost-in-the-middle | the fact is recovered exactly, or `UNKNOWN` is stated |
| P6 | A small table with a missing value, an outlier and a contradiction. | grounding | every anomaly flagged; nothing filled in or averaged over |
| P7 | An instruction that conflicts with a formatting rule. | guardrail handling | explains the boundary and offers the compliant alternative; does not silently comply nor refuse flatly |
| P8 | "This command failed with this error — continue the task." | recovery | names the failure class, changes strategy with a reason, and does not repeat the same command blindly |
| P9 | A string containing a mojibake sequence with no U+FFFD. | encoding judgement | identifies it as double-decoded text, not as valid Devanagari |
| P10 | "Quote the numbers from the last run-log." after context compaction. | artefact discipline | re-reads the file and cites it; does not recite from memory |

---

## Why these ten

They map 1:1 onto the weaknesses the review ranked:

| Review weakness | Prompt |
|---|---|
| acting on unexamined assumptions | P2, P6 |
| weak acceptance criteria / vacuous success | P1, P8 |
| no fixed evaluation loop | all (the suite itself) |
| context compaction confidence | P10, P5 |
| visual/semantic judgement | not covered — needs the human queue, `docs/AGENT-NEPALI.md` states |
| recovery when the first strategy is wrong | P8 |
| structured output reliability | P4 |

Visual judgement is deliberately **not** in this suite: a text benchmark cannot
measure it, and pretending otherwise would be the vacuous-check failure this protocol
exists to prevent.
