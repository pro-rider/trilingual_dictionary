# SECURITY CONTRACT — production-database guard

The agent must never open `dictionary.sqlite` or `translations.db`, in any form.
The guard previously decided by filename and path fragment, and three tests
showed it could be walked past.

## Controls, in order

1. **Ambiguity refusal** (`AmbiguousPathRefused`)
   - empty or non-string path;
   - leading/trailing whitespace;
   - any control character;
   - `file:` prefix or any `://`;
   - any `?` or `#` (SQLite URI query/fragment syntax).
2. **Name and marker rules** (`ProductionDatabaseRefused`)
   - filename in `{dictionary.sqlite, translations.db}` (case-insensitive, after
     `realpath`);
   - resolved path containing `backend/data/build` or `assets/data` (backslashes
     normalised, so Windows separators are covered).
3. **Identity rules** (`ProductionDatabaseRefused`), against the protected
   manifest:
   - the resolved path is listed;
   - `(st_dev, st_ino)` equals a listed entry → catches **hard links**, which no
     path rule can see;
   - size matches and `sha256` matches → catches **byte-identical copies**.
4. **Fail-closed rules** (`UnverifiableProtectedIdentity`)
   - the target exists but cannot be stat'ed;
   - the target exists but is not a regular file;
   - an explicitly configured manifest is missing or unparseable.

## The manifest

`protected-databases.json`, produced by `scripts/protect_manifest.py` on the
machine that holds the real database:

```json
{"manifest_schema_version": 1, "tool_version": "0.1", "captured_at": "...",
 "entries": [{"path": "...", "dev": 123, "ino": 456, "bytes": 100769792, "sha256": "..."}]}
```

Set `TRANSLATION_AGENT_PROTECTED_MANIFEST` to point at it. Without a manifest the
guard still refuses by name, marker and ambiguity, but **hard-link protection is
not available** and `manifest_coverage()` reports that explicitly
(`hardlink_protection: false`). Never report hard-link protection as active
without the flag saying so.

## What identity protection cannot do

- A manifest entry whose `dev`/`ino` was captured before the file was replaced
  is stale; the `sha256` check covers that case only if the hash was refreshed.
- On filesystems that report `st_ino = 0` (some Windows network shares), inode
  comparison degenerates; the hash check still applies but costs a full read.
- A writable bind mount or a filesystem-level clone that changes inode **and**
  content is indistinguishable from a legitimate ledger. Defence in depth is
  filesystem permissions, not path logic.

## Verified behaviour (executed)

`tests/security/test_guard_bypass.py`: absolute, relative, `.`/`..`, symlink,
mixed separators, uppercase name, same name in an unrelated directory, env
override, `file:` URI, `?mode=rw`, trailing whitespace, hard link, byte-identical
copy, manifest-listed path, unreadable manifest, missing explicit manifest —
all refused. An unrelated temp database is allowed.
`tests/test_security.py` covers the CLI-level refusal and the structural guard
that `sqlite3.connect` appears only in the ledger module.

## Operations (manifest lifecycle)

1. **Capture on the machine that owns the database**, never on a copy:
   `python scripts/protect_manifest.py --db <real path> --out protected-databases.json`
   (the tool refuses to hash a path it cannot read and records `dev`, `ino`,
   `bytes`, `sha256`, `captured_at`).
2. **Export the path** in `TRANSLATION_AGENT_PROTECTED_MANIFEST`; keep the file
   readable only by the operator account — it is a map of the protected files.
3. **Re-capture after any legitimate change** to a protected database (rebuild,
   migration, restore). `guard` reports `age_days` and `stale` (threshold 30 days);
   a stale manifest is a warning, not a refusal, because refusing would block
   work on a database that merely aged.
4. **Treat a stale manifest as unprotected for inode purposes** in any report:
   say `stale: true` instead of claiming hard-link protection.
5. **Verify after capture**: `guard` must print `entries > 0`, `inode_identity
   true`, `content_identity true`, `hardlink_protection true`. If any is false,
   that protection is not active — report it as absent, do not assume it.

Malformed manifests (missing `entries`, entry without `path`, non-integer
`dev`/`ino`/`bytes`, sha256 that is not 64 hex characters) fail closed before
any connection is attempted.
