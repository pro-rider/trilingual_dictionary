# FINGERPRINT CONTRACT

Two identities live in this subsystem, and they answer different questions.

| identity | version | question |
| --- | --- | --- |
| `candidate_hash` | 1 | is this the same *normalized text*? |
| `request_fingerprint` (v1) | 1 | is this the same *generation configuration*? |
| `request_fingerprint` (v2) | 2 | is this the same *generation input*? |

None of them is the production `content_fingerprint` (v1) defined in
`backend/app/translations/schema.py`. That one hashes database *contents*
(length-prefixed fields, `fingerprint_version=1`). These hash *requests and
candidates*. They are never compared and never share a version namespace.

## v1 — frozen

```
sha256(canonical_json{
  fingerprint_version: 1,
  sense_key, target_language, provider, model,
  prompt_version, prompt_checksum
})
```

Frozen because stored values depend on it. Recomputing it under a new algorithm
would silently invalidate history. New rows carry v1 in
`generation_requests.request_fingerprint_v1` next to the v2 value.

## v2 — input-aware

```
sha256(canonical_json{
  fingerprint_version: 2,
  normalization_version: "nfc-ws1-v1",
  sense_key,
  source_word, source_pinyin, source_gloss,      # normalized, NFC + ws-collapsed
  source_revision_hash,                          # sha256 over the source triple
  target_language, provider, model, model_parameters,
  prompt_version, prompt_checksum,
  rendered_prompt_sha256,                        # sha256 of the exact prompt sent
  output_schema_version: "candidate-json-v1",
  variant_key                                     # null for the base variant
})
```

Why each field is present:

- **source fields + revision hash**: a corrected gloss must produce a new
  request. Without them, a stale candidate is silently reused (the v1 defect).
- **rendered prompt hash**: catches a template change that leaves the template
  checksum unchanged but alters the actual text for a specific sense.
- **model parameters**: resolved settings (temperature, top_p, max_tokens, ...)
  come from `provider.parameters()`, are stored as canonical JSON in
  `generation_requests.model_parameters`, and are hashed into v2. Changing one
  changes the request — proven end to end by
  `tests/test_fingerprint_v2.py::test_changing_a_generation_parameter_changes_the_request`.
  `None` is no longer accepted: a provider that has no settings returns `{}`.
- **variant key**: an intentional second generation is a different request; it
  must not look like a duplicate.

`canonical_json` is the frozen serialization used everywhere here: sorted keys,
no whitespace, `ensure_ascii=False`, NaN refused. Normalization is
`nfc-ws1-v1` (NFC, whitespace collapse, no case/diacritic/NFKC folding).

## Rules

1. Never change v1 or v2 in place. A new algorithm is a new version number.
2. Never compare a candidate hash with a request fingerprint.
3. Never reuse the production fingerprint namespace; different names, different
   versions.
4. A change to prompt text, model, or normalization is an identity change and
   therefore a new pilot.
