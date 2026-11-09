# PILOT PROTOCOL — 50 senses, pre-registered

Status: DRAFT, pre-registered. Written **before** any real sense is processed.
Nothing here is measured yet.

Every item is in exactly one of three states:

- **FIXED BY IMPLEMENTATION** — the code already enforces it; changing it is a
  code change, not a preference, and it voids this protocol.
- **HUMAN DECISION REQUIRED** — only you can decide; it blocks the stage named.
- **PROPOSAL** — a default I recommend; still needs your yes/no.

If the prompt, the model, the validator, the normalization version, or the
selection seed changes, this protocol is void and a new one must be written
before the next run. Writing criteria after seeing results invalidates them.

## (a) Scope — FIXED

- Exactly **50 source senses**, one candidate each per variant, target language `ne`.
- Two stages, never merged:
  1. **Plumbing check** — fake provider, real senses. Proves the pipeline and
     ledger behave on real keys. Produces **no** translation evidence.
  2. **Real-provider pilot** — the 50 senses through one real provider/model.
- Out of scope: import into `translations.db`, any UI change, any second batch
  without approval.

## (b) Selection of the 50 — OPEN (blocks TASK 016 only)

- Method: **HUMAN DECISION REQUIRED** — (i) deterministic sample from the
  2,477 HSK-tagged entries; (ii) sample stratified by gloss length bands;
  (iii) sample from the 2,737 senses inside HSK entries minus the 3,245 already
  translated. Recommendation: (iii) — it stays inside the vocabulary band the
  app already claims, and avoids re-translating existing rows.
- Seed: recorded in the selection manifest; the sample must be reproducible from
  `(seed, method, source query)`.
- Stratification variables: gloss token length (≤2 / 3–5 / ≥6 words), polysemy
  count per headword, and known-defect category. Part of speech is **not usable**:
  `pos_primary` is empty for 198,230 of 198,306 senses, so it cannot stratify
  anything and must not be claimed as a stratification axis.
- Constraint: ≥ 10 of the 50 are concrete nouns, so a later image phase has
  material.
- Inclusion rules: **HUMAN DECISION REQUIRED** — whether the two `foreign_token`
  senses (5090 `सूची अक्षर C`, 49650 `Zhuge Liang को सम्मान नाम`) may appear at
  all, and whether any of the five `intra_token_mix` senses
  (59001, 66092, 112935, 112963, 170710) are excluded up front rather than
  quarantined during the run.

## (c) Selection of the 20 review samples — FIXED (mechanism), seed OPEN

- Seeded, stratified subset of the 50 — never "the first 20".
- **Every** candidate the validator flagged (`quarantined`) joins the review set
  on top of the 20. This is enforced by the export contract, not by prose.
- The manifest records candidate_id, sense_key, stratum and inclusion reason
  (`sampled` | `flagged`).
- The seed value itself is **HUMAN DECISION REQUIRED** (or you may authorise me
  to derive it deterministically from the selection seed).

## (d) Mechanical criteria — FIXED (script-checkable)

| criterion | required | where enforced |
| --- | --- | --- |
| Latin/Cyrillic leaks among candidates marked `ok` | 0 | validator (`latin_in_output`, `cyrillic_in_output`) |
| Provenance fields populated per candidate | 100 % | ledger NOT NULL + `find_candidate_by_identity` |
| Writes to protected paths | 0 | `config.assert_not_production` (name, marker, identity, ambiguity) |
| Database pins identical before and after | required | `scripts/capture_pins.py` + `safe_copy.py` |
| Candidates moved to `approved`/`imported` by the agent | 0 | state machine (`generation_agent` has no such edge) |
| Request identity covers the resolved input | required | request fingerprint v2 + stored `model_parameters` |

A failure stops the pilot; it is not discussed away.

## (e) Human criteria — OPEN

- Reviewer qualification: **HUMAN DECISION REQUIRED** — proposal: native Nepali
  speaker with working English and Chinese reading ability. With a single
  reviewer, **no agreement statistic may be claimed**.
- Rating scale — FIXED: **accept** / **edit-needed** / **reject**, with one reason
  code from `wrong_sense`, `hindi_not_nepali`, `transliteration`, `register`,
  `mixed_script`, `too_literal`, `other`.
- Thresholds — **PROPOSAL, needs approval**:
  - proceed to 500: source-sense alignment ≥ 95 %, target acceptability ≥ 90 %,
    severe meaning errors among accepted candidates = 0.
  - pause and revise: acceptability 70–90 %.
  - stop the approach: acceptability < 70 %, or any severe meaning error in a
    candidate that would otherwise have been accepted.
- **HUMAN DECISION REQUIRED** — whether all 20 must be reviewed before
  proceeding, or 19/20 with one clear reject is sufficient.

## (f) Stop conditions

**FIXED**: any guard refusal, any pin drift, any unexpected file change, provider
error rate > 5 % of requests, > 20 % of candidates quarantined by mechanical
validation, any crash whose resulting ledger state a re-run cannot explain.

**HUMAN DECISION REQUIRED (blocks real-provider stage only)**: the cost cap
value and the rate limit. Until both are set in configuration and confirmed by
you, TASK 018 must not start.

## (g) Prompt and version policy — FIXED

Any change to the prompt template or version, model name, resolved generation
parameters, validator rules, or normalization version invalidates the pilot.
A new pilot with a new record is required; results from two versions may not be
compared inside one pilot.

## (h) Data handling

- What leaves the machine — FIXED: `simplified` headword, `pinyin`, and the
  English gloss for the 50 senses. Nothing else.
- Licence status of the English glosses: **UNKNOWN** — **HUMAN DECISION
  REQUIRED** before any real provider sees them. Blocks TASK 018.
- Privacy / data-processing terms of the chosen provider: **HUMAN DECISION
  REQUIRED** (which provider, which region, whether data may be retained by the
  vendor for training). Blocks TASK 018.
- Raw responses: redacted, size-capped (16,384 B), retained for audit;
  retention **PROPOSAL 30 days**, then payload purge via
  `translation_agent.cli retention --apply`. Enforcement exists
  (`audit/retention.py`); the operation is never automatic.
- API key: environment variable only; never written to a file, a log, or a report.
  The staged CI fails if any provider-key variable is present.

## (i) What this pilot cannot prove — FIXED statement

- That 3,245 senses, or any larger population, will reach the same quality.
- That mechanical validation implies correctness: it cannot see meaning.
- That a single reviewer's judgement generalises.
- That the provider is stable across model versions.
- That the Windows/NTFS identity checks behave like the Linux tests.

## (j) Escalation path — FIXED

`50 → 500 → 3,245`, each step gated by a human approval after reading the
previous report. No automatic progression; batch size grows only after the
previous batch's human review is recorded.

## Decision register

| # | item | state | blocks |
| --- | --- | --- | --- |
| 1 | selection method for the 50 | OPEN (rec. HSK-entry senses without Nepali) | 016 |
| 2 | selection seed value | OPEN | 016 |
| 3 | `foreign_token` / `intra_token_mix` inclusion | OPEN | 016 |
| 4 | 20-sample seed | OPEN | 018 |
| 5 | reviewer identity + qualification, one reviewer enough? | OPEN | 018 |
| 6 | thresholds 90 % / 70 % | PROPOSAL | 018 |
| 7 | review all 20 vs 19/20 | OPEN | 018 |
| 8 | cost cap | OPEN | 018 |
| 9 | rate limit | OPEN | 018 |
| 10 | raw-response retention (proposal 30 d) | PROPOSAL (code ready) | 018 |
| 11 | English gloss licence for third-party processing | OPEN, currently UNKNOWN | 018 |
| 12 | provider + model + region, privacy terms | OPEN | 018 |
| 13 | whether `pos_primary` may be used as a stratum | **RESOLVED: no** — 198,230/198,306 empty | — |
| 14 | whether quarantine failures may be silently retried away | **RESOLVED: no** — flagged candidates are always reviewed | — |

Items 13–14 were settled by evidence and code, not by preference; reversing them
requires a code change and voids the protocol.
