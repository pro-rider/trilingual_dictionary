# Privacy policy — DRAFT

**DRAFT, needs human/legal review.** Placeholders such as `[CONTACT_EMAIL]`,
`[APP_NAME]` and `[COMPANY_LEGAL_NAME]` must be filled before publishing.
The in-app summary in `lib/features/settings/settings_screen.dart`
(`_showPrivacySummary`) says the same things in fewer words and must stay
consistent with this document.

## What the app does by default

The dictionary is bundled with the app. Searching, browsing an entry, reading a
definition or an example, viewing a saved word and viewing history all work
offline and send nothing to a server.

## When data leaves the device

Only these actions send text to a third party, and only when you trigger them:

| Action | What is sent | Where it goes |
|---|---|---|
| Ask AI for a missing translation / example | the word or sentence you typed, plus the language pair | a third-party language-model provider |
| Analyze a passage | the passage you pasted | the same provider |
| (optional) cloud sync of favourites | your account id and the list of saved word ids | the configured database provider |

Nothing else is transmitted. The app does not send your search history, your
saved words, or any file from your device.

## What the server keeps

The backend keeps **counters only**: how many AI requests were made per device
or IP address in a minute and in a day, so one heavy user cannot exhaust a free
tier for everyone. The text you typed is not written to any server log, and
`docs/` records this as a rule the code must keep (the rate limiter logs only
scope, key and reason, never content).

## What stays on your device

| Data | Where |
|---|---|
| Favourite words | app preferences (`favorites`) |
| Search history | app preferences (`history`) |
| AI results you generated (translations, examples) | local `user.db` on the device |
| The dictionary itself | an unpacked copy inside app storage |

Uninstalling the app deletes all of it. A dictionary upgrade replaces only the
bundled database copy; `user.db` and preferences are never modified by an
upgrade.

## Retention

Server counters are kept for at most 24 hours (a rolling minute window and a
daily counter that resets each day). No other server-side storage exists.

## Children

The app is a reference dictionary and is not directed at children under 13. It
collects no personal information; the only text sent to a third party is text a
user chooses to submit.

## Your choices

You can disable AI features (Settings → Offline-first search stays on; AI is only
called from an explicit action). With AI unused, the app makes no network
requests at all.

## Contact

Questions or deletion requests: **[CONTACT_EMAIL]**

Last updated: draft, 2026-11-12.
