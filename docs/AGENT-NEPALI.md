# Nepali enrichment agent — structure

Status: structure agreed, first measurement done, no code beyond the probe.
Target field: **Nepali gloss only** (v1). Runtime: local machine, existing LLM keys.
Promotion: high-confidence auto-into-pack + spot-check sample.
Sources: structured open sources only — **this is the decision the measurement
below puts in question.**

## Why it does not run inside the app

The agent is a batch producer, not a request handler:

```
agent_targets (from dictionary.sqlite gaps)
      ↓  tools: fetch evidence from licensed sources
evidence (url, license, snippet, fetched_at)
      ↓  extract value from evidence; cite it
enrichment_proposals (value_ne, confidence, checks, status)
      ↓  deterministic gates
approved → delta pack (SQLite patch, stable sense keys)
      ↓
app downloads the pack; never calls the agent; offline rule holds
```

Nothing writes to `data/build/dictionary.sqlite`. The app keeps its rule from
G1: user data in `user.db`, dictionary content in the packaged file plus
downloaded delta packs.

## Layers

1. **Target selector.** Reads gaps from the real database and writes a queue.
   A target is `(stable sense key, simplified, pinyin, gloss_en, band)`.
   Queue order is *the order users actually look words up*, not row order:
   top 5,000 by `freq_rank` first, then HSK bands, then the tail.
2. **Tool layer.** One module per source, each returning `Evidence`
   (value candidate, URL, licence, retrieved-at, raw snippet). No free-form
   page text ever reaches the model; only snippets do.
3. **Extractor.** LLM call with a strict JSON schema
   (`value_ne`, `chosen_evidence_id`, `confidence`, `reason`). The model may
   not invent a value that is not in the supplied evidence; it may only
   translate, which is labelled separately (`ai_translated`).
4. **Verifier — deterministic, never AI.** Devanagari-only (no Latin, no
   digits), 1–40 characters, not a copy of the English gloss, no
   duplicate-with-different-gloss inside the same word, back-translation
   similarity above threshold (one extra LLM call used as a *checker*), and
   `ne_status` derived from which gate it passed.
5. **Writer.** Only `enrichment_proposals` + `evidence`. Never overwrites a
   row whose `review_status='reviewed'`.
6. **Pack builder.** Approved proposals → delta pack with a manifest
   (version, counts, licence list); the app merges by stable sense key, the
   same mechanism as G1.

## Tables (agent.db, separate file)

```sql
agent_targets(target_key PK, entry_id, simplified, pinyin, gloss_en, band,
              field, state, tries, last_error, updated_at)
evidence(evidence_id PK, target_key, source, url, license, fetched_at,
         snippet, http_status)
enrichment_proposals(proposal_id PK, target_key, field, value_en, value_ne,
                     confidence, model, provider, status, checks_json,
                     reviewer, created_at)
agent_runs(run_id PK, band, started_at, finished_at, targets, verified,
           quarantined, approved, cost_usd)
```

States: `proposed → verified → approved | rejected | quarantined`,
plus `needs_human` for the spot-check tier.

## What the measurement found (25 real top-5,000 targets)

`backend/tools/ne_source_yield.py`, CSV in `%TEMP%\ne_source_yield.csv`.

| Source | Apparent hit | Real hit |
|---|---|---|
| en.wiktionary "Nepali" translation cell | 6/25 (24%) | **0/25** — every hit was a neighbouring `Bokmål: å (no)` cell caught by the regex |
| ne.wiktionary full-text search | 4/25 (16%) | **0/25** — returned dictionary *page titles* like `नेपाली - इंग`, not the word |

So: **structured open sources contain essentially no Nepali for CC-CEDICT
glosses.** That is the same reason only 3,245 of 198,306 senses have a Nepali
gloss today. "Search online for the missing data" is not available in
license-clean form at this scale; the only real producer of Nepali here is
translation, and it must be labelled and checked as such.

## Two data defects the queue exposed

Both block "measure where users look" and must be fixed before any gate can be
set (G2/G3):

* `entries.hsk_level` is non-null on 2,477 entries and **all of them are 5**.
  HSK 1–3 queues are empty, and an HSK-based launch gate cannot be computed.
* `entries.pos_primary` is empty on **123,596 of 123,672** entries (40 tagged
  noun). Any "concrete noun" filter — G7 images, and choosing which glosses
  deserve a Nepali value — currently has nothing to filter on.

Ordering by raw `freq_rank` also surfaces grammar particles first (`的` has
seven senses at rank 1), so the queue needs a POS/category signal to skip
function words.

## Revised plan

1. **Fix the two columns first** (small, deterministic, no AI): HSK level per
   entry from the official list, POS from CC-CEDICT's `pos` markers. Without
   them the agent cannot target anything meaningful.
2. **Invert the source weighting.** Primary value = LLM translation with a
   termbase; structured sources become *corroboration* (if a licensed source
   happens to agree, confidence rises). This is what the data supports, and it
   keeps the licence story clean: no third-party dictionary text is copied.
3. **Prove the loop on 200 real targets** before scaling: measure
   accept rate, quarantine reasons, and cost per 1,000 glosses.
4. Keep the gates in the verifier, not in the prompt.
