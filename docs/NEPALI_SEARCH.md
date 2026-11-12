# Nepali as a search input — feasibility note

**Status: not implemented.** This is a decision document only, per the release
instruction ("write a 1-page feasibility note, do NOT implement"). Facts below
were read from the shipped database on 2026-11-12.

## What exists today

| Fact | Value |
|---|---|
| senses with a Nepali gloss | 3,245 of 198,306 (1.64%) |
| distinct Nepali gloss strings | ~2,746 |
| review status of those glosses | 100% `ai_translated`, 0 `reviewed` |
| an index over Nepali text | none — `fts` covers `simplified`, `traditional`, `pinyin_search`, `english`, `category`; `fts_zh` covers `simplified`, `traditional`, `english` |
| Nepali in the client search path | none: search accepts Latin, Hanzi and pinyin only |

So the honest starting point is: **the dictionary barely contains Nepali, and
what it contains is unreviewed machine output.** A Nepali search box would
mostly return nothing, and occasionally return an unverified guess.

## Why the naive implementation is misleading

Nepali search needs *word-level* matching against Devanagari text. SQLite FTS5's
`unicode61` tokenizer does not segment Devanagari conjuncts reliably, and a
trigram index over a 2,746-string column would produce false positives
(`="समाज"` matching inside `समाजवाद`). The realistic options are:

1. a small Devanagari normaliser (strip ZWJ/ZWNJ, unify न/ऩ variants) plus exact
   and prefix lookup on a new `gloss_ne_norm` column + index;
2. a proper Nepali stemmer, which is a research-grade dependency (no maintained
   pure-Python Nepali stemmer is well tested at this scale).

Option 1 is a day of work and honest. Option 2 is over-engineering for 2,746
strings.

## The real blocker is data, not search

If Nepali search shipped tomorrow, a Nepali speaker typing a common word would
usually get "not found" — because 1.64% coverage is not a searchable dictionary.
Worse, the 3,245 existing glosses are machine translations awaiting native
review, so a Nepali **speaker** is the exact audience who would immediately see
the errors.

## Recommendation

1. **Do not ship Nepali input** in this release. Document the behaviour instead:
   the search box already tells the user which languages it accepts.
2. **Sequence it after review**: once a meaningful share of the launch set has
   `ne_status = 'reviewed'`, revisit.
3. When revisited, build it as: `gloss_ne_norm` column + exact/prefix index +
   a normaliser, with a "showing machine translations (pending review)" banner
   on results — never as a silent equivalent of an English search.

## Cost estimate

| step | effort | dependency |
|---|---|---|
| normaliser + `gloss_ne_norm` + index + query path | ~1 day | none |
| adding the field to the release build and assetVersion | ~2 h | Phase 7 pipeline (exists) |
| accuracy evaluation | needs a native speaker | **human, not code** |
