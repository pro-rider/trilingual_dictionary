# INTEGRATION CONTRACT (v0.1)

The agent exports; the parent application imports. That separation is the whole
safety argument, and it is enforced here: this subsystem has no import function
and cannot open `translations.db` or `dictionary.sqlite`.

## Direction of flow

```
dictionary.sqlite (read-only, outside this subsystem)
        │  sense rows, chosen by a parent-owned sampler
        ▼
translation_agent  ──►  candidates.db        (candidate ledger, this subsystem)
        │
        │  export (approved only, checksummed manifest)
        ▼
parent-owned importer  ──►  translations.db  (governance store, parent only)
        │
        ▼
LocalTranslationRepository / resolve_values  ──►  Flutter display paths
```

## Export requirements

- Only `state = 'approved'` rows are exported. Zero approved rows ⇒ `ExportRefused`,
  non-zero exit. Verified by `tests/test_security.py`.
- Each exported candidate carries: `candidate_id`, `sense_key`, `target_language`,
  `text`, `normalized_text`, `normalization_version`, `candidate_hash`,
  `request_id`, `batch_id`.
- The manifest carries `contract_version`, `exported_at`, `candidate_count`,
  and `export_checksum = sha256(canonical_json(manifest without checksum))`.

## Import requirements (parent side, not implemented here)

1. Verify the export checksum against the manifest body.
2. Reject any candidate whose `sense_key` is unknown to the dictionary.
3. Refuse to overwrite an existing non-empty `gloss_ne` for that sense.
4. Write with `generation_method = 'llm'`, `evidence_strength = 'none'`,
   `validation_status = 'incomplete'`, `publication_status = 'labeled'`,
   `human_verification = 'not_verified'`, plus the export's provenance fields.
5. Import in one transaction per batch; a failure leaves no rows.
6. Verify the database pins before and after; any drift aborts the import.

## Non-negotiable separations

- **Candidate quarantine ≠ production quarantine.** A quarantined candidate is
  simply absent from the export. It never creates or suppresses a production
  row, and it never makes production text invisible.
- **Human verification ≠ candidate approval.** Approving a candidate means
  "this text may be imported as labeled AI content". It does not mean
  `human_verification = 'verified'`; nothing in this subsystem can set that.
- **Two fingerprints, two meanings.** `content_fingerprint` (production, v1,
  length-prefixed fields, hashes database contents) and `candidate_hash` /
  `request_fingerprint` (this subsystem, canonical JSON, hashes text and
  requests) are never compared, never substituted for each other.
- **Display paths.** Approved-and-imported rows reach the app only through
  `LocalTranslationRepository` / `resolve_values`; the agent never touches a
  widget, a badge, or a search index.
