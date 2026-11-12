# Assumptions

Decisions taken without asking, because a wrong guess would have been cheap to
reverse. Anything expensive or ambiguous was escalated instead (see
`docs/BLOCKED.md` and `docs/HUMAN_TODO.md`).

| # | Date | Assumption | Why it was safe | How to reverse |
|---|---|---|---|---|
| A1 | 2026-11-12 | "Launch set" is stored inside `dictionary.sqlite` as table `launch_set`, and dropped from the release build like every other planning table | It is a planning artifact, not shipped data; keeping it in the working DB makes every later phase able to report progress against it | `tools/build_launch_set.py --drop` or rebuild the release DB |
| A2 | 2026-11-12 | Tier 1 = every entry with `hsk_level` set (2,477). Tier 2 = the next entries by `freq_rank` up to 5,000 total. Tier 3 = everything else | Matches the user's stated rule (HSK first, then top ~5,000 by frequency) without inventing a new frequency source | Re-run `tools/build_launch_set.py` with a different tier boundary |
| A3 | 2026-11-12 | Chinese Wiktionary text is imported into `senses.gloss_zh` only above a confidence threshold, and every imported row is recorded in `gloss_provenance` with source and license | The user authorised importing the safe rows; provenance keeps the license auditable per row | Delete rows listed in `gloss_provenance` for source `zh.wiktionary` |
| A4 | 2026-11-12 | The top 10,000 by `freq_rank` are never auto-imported, even when a Wiktionary gloss exists | The user's own finding: the gloss for high-frequency function words is often archaic (`的` → "白色；箭靶中心") | Lower the exclusion in `tools/import_wiktionary_zh.py --auto-max-rank` |
| A5 | 2026-11-12 | Missing Chinese definition in the client must render an explicit empty state, not repeat the headword | Rule from the brief; a repeated headword reads as a real definition and hides the gap | Client change is isolated in one widget |
| A6 | 2026-11-12 | Review files are capped at 500 rows per file and split by topic, named `<topic>-<part>.xlsx` | Keeps review sessions short; matches the existing Nepali review sheet format | Re-run `tools/build_review_packages.py --chunk 1000` |
| A7 | 2026-11-12 | `review_audit` and `review_rejected` live in the working DB only; the release build drops them | Audit needs to survive between review rounds, but must not ship user data | Release build config lists them as dropped |
| A8 | 2026-11-12 | No AI provider is used for bulk generation in this run, because every configured provider failed a real probe | Rule 1 forbids inventing content; providers are documented as blocked | Re-run once a working key exists |
| A9 | 2026-11-12 | Play Store / legal documents are drafted as `DRAFT — needs human/legal review` and never presented as final | Legal sign-off is a human step | Review and approve the drafts |
| A10 | 2026-11-12 | Nepali as a *search input* is not implemented this run; only a feasibility note is written | The brief explicitly says to ask before implementing | Implement later if approved |
