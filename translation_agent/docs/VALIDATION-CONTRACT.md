# VALIDATION CONTRACT (v0.1)

Mechanical validation only. It protects the shipped assets; it does not judge
language quality and it cannot approve anything.

## Codes (first match wins)

| code | condition |
| --- | --- |
| `not_text` | candidate is not a string |
| `empty` | empty or whitespace-only |
| `too_long` | > 200 characters |
| `cyrillic_in_output` | any U+0400–U+04FF character |
| `latin_in_output` | any `[A-Za-z]` character |
| `no_devanagari` | no character in U+0900–U+097F |
| `script_mix` | any character outside Devanagari + allowed punctuation/joiners |
| `echo_source` | normalized candidate equals the normalized English gloss |
| `ok` | passed all checks |

Allowed beyond Devanagari: danda, Devanagari digits, ZWNJ/ZWJ (U+200C/200D),
NBSP, ASCII spaces and `. , ! ? ; : ' " ( ) - – — /`, typographic quotes, ellipsis.

## Why `cyrillic_in_output` precedes `latin_in_output`

The real defect class found in production is text like `पурсnu` and `बatti`:
a Devanagari token spliced with Latin or Cyrillic letters. Reporting the rarer
script first makes the report more informative; both still quarantine the
candidate.

## Consequences

A failing candidate is stored with state `quarantined` and an audit event
carrying `"<code>: <reason>"`. It is never exported, never approved, and never
written to production by anything in this subsystem.

## What this does *not* prove

- That the Nepali is natural, idiomatic or correct for the sense.
- That the sense was interpreted correctly.
- That the text is not a duplicate of a different sense's translation.

Those are human-review questions. The pilot acceptance criteria (source-sense
alignment ≥ 95 %, target-language acceptability ≥ 90 %, zero severe meaning
errors in approved candidates) are measured by reviewers, not by this module.
