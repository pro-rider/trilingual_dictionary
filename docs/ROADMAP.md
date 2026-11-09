# Gap roadmap and status

Source: the review that ranked the gaps (Nepali coverage, examples, images,
personalization, hi-res images, accuracy) and the G1–G13 roadmap.

Status legend: **done** · **partly** · **not started**

| # | Item | Status | Evidence / where |
|---|---|---|---|
| G1 | User data separated from dictionary updates | **done (core)** | `lib/data/local/user_store.dart`, `docs/G1-USER-DATA.md`, `test/user_store_test.dart` (5 tests) |
| G2 | Accuracy harness + launch gates | **partly** | offline analyser tests only; no locked query set, no coverage dashboard |
| G3 | Dictionary data quality audit | **partly** | deterministic example gate (`clean_examples.py`), `quarantine_reason`; no full audit |
| G4 | Search ranking | **partly** | gloss scoring + banded frequency ranking in `_bestEnglishRow`; no recall measurement, no typo tolerance |
| G5 | Nepali coverage (HSK 1-6 → top 20k) | **not started** | 3,245 / 198,306 senses |
| G6 | Examples with a review workflow | **partly** | gate + statuses exist; 375 words, `review_status` mostly `imported` |
| G7 | Images by concept, not frequency | **partly** | concept/P18/sibling index built; 204 words; no concrete-noun target list, no OpenMoji fallback |
| G8 | On-demand hi-res + cache | **not started** | thumbnails only |
| G9 | Personalization | **not started** | spec captured, no code |
| G10 | Learning features | **not started** | — |
| G11 | Speech reliability | **partly** | single TTS service, diagnostics screen; no tap-to-sound measurement |
| G12 | Backend hardening | **partly** | AI fallback exists; no auth, rate limits, pending table |
| G13 | Licensing, privacy, release | **partly** | per-image attribution on screen; no credits screen, no privacy policy |

## Launch gates to adopt (measured on the real database)

* HSK 1–3: 100% of senses with a Nepali gloss; HSK 4–6: 95%.
* Top 5,000 words by frequency: every word with at least one visible example.
* HSK 1–4 concrete nouns: an image or icon for each.
* Search recall@1 ≥ 90% on a locked 300-query set; p95 latency < 100 ms.
* Build fails when any gate regresses (G2 harness writes the numbers).

## Coverage, measured where users actually look

| Band | Words | With image | With example | With Nepali gloss |
|---|---|---|---|---|
| HSK 1–2 | 1,500 | to measure | to measure | to measure |
| HSK 3–4 | 1,000 | to measure | to measure | to measure |
| HSK 5–6 | 2,500 | to measure | to measure | to measure |
| Top 5,000 by frequency | 5,000 | to measure | to measure | to measure |

The dashboard that produces these numbers is G2; the numbers above are the
gates it must enforce. Measuring the whole 123,672-word tail is a later problem.
