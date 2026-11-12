# Play Console "Data safety" — draft answers

**DRAFT, needs human review before it is typed into Play Console.** Answer
questions exactly as written here only after checking each one against the
shipped build. Where an answer depends on a choice the team has not made yet, it
is marked **DECISION NEEDED**.

## Section 1 — Data collection and sharing

Question: does your app collect or share any of the required user data types?

**Answer: Yes.** Text a user submits to an AI feature is sent to a third-party
provider. Everything else is on-device only.

| Data type | Collected? | Shared? | Purpose | Notes |
|---|---|---|---|---|
| Text messages / in-app content (the word or sentence typed for AI) | Yes | Yes | App functionality | Ephemeral, used to answer the request; not stored on the server |
| Search history | No — on-device only | No | — | Stored in app preferences |
| Favourites | **DECISION NEEDED** — if cloud sync is enabled for the release, "Yes"; the code path exists but Supabase is not configured | Same | App functionality | Local storage always happens |
| Approximate location | No | No | — | Not requested |
| Device or other IDs | **DECISION NEEDED** — the backend rate limiter sees the IP address; it is used only to count requests per hour/day | No | Abuse prevention | Not stored with content; counters reset daily |
| Crash logs / diagnostics | **DECISION NEEDED** — see below | — | — | Only if crash reporting is enabled before release |

## Section 2 — Encryption and deletion

- Is all data encrypted in transit? **Yes** — all provider and backend traffic is
  HTTPS.
- Can users request data deletion? **Yes** — uninstalling the app deletes every
  on-device record. If cloud sync ships, a deletion-request contact is
  `[CONTACT_EMAIL]`.
- Is data processed ephemerally? **Yes** for AI text; **No** for on-device
  favourites/history (kept until the app is uninstalled).

## Section 3 — Third parties

| Provider | Role | Data received |
|---|---|---|
| Language-model provider(s) actually configured in the release build | Processor | The submitted word/sentence |
| **DECISION NEEDED**: hosting provider of the backend | Processor | Request metadata only |

The release currently has **no working paid provider configured** (see
`docs/BLOCKED.md`), so this table must be filled in when the key is chosen.

## Section 4 — Statements that must stay true

1. No user text appears in server logs. Verified by review of
   `backend/app/core/ai_guard.py` (logs scope/key/reason only) — re-verify after
   any logging change.
2. The bundled dictionary contains no licence-restricted material. Verified by
   `backend/tests/test_release_license_audit.py` and the build-time audit.
3. The app works fully offline for dictionary content.

## Section 5 — Crash reporting (Phase 10 hook)

A hook exists but no crash-reporting SDK is installed. **DECISION NEEDED:** ship
without crash reporting (simplest answer above), or add an SDK and then re-answer
Section 1 with "Crash logs: collected".
