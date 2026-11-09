"""One resolution rule for "which Nepali text do we show for this sense?".

Every caller — the HTTP API, reports and (mirrored) the Flutter repository — must
go through this instead of merging the dictionary and the governance store by
itself. The rule is deterministic and ordered:

1. Candidate rows for the sense are its ``language='ne'`` rows in the store.
2. A row is *active* when nothing supersedes it (it is the leaf of its chain).
3. Quarantined leaves are never shown.
4. Among the remaining leaves, a human-verified row wins; otherwise the newest
   ``translation_id`` wins. There is at most one leaf per chain (trigger
   enforced), so "newest" cannot pick between two branches of the same chain.
5. If the store has nothing showable, the dictionary's original value is shown
   with the ``unverified_legacy`` label — the store missing a row is normal
   (a sense never imported), not an error.
6. A row superseded by a newer one is still returned in ``history`` so the
   original value stays reachable and auditable.

User references (bookmarks, history, notes) resolve by the same rule: a stored
``translation_id`` is translated to its chain's active leaf, and the referenced
row itself is kept so "show the old value" is still possible. Ids are never
rewritten in user data.
"""
from __future__ import annotations

from . import status

LANGUAGE = "ne"


def _rows(conn, sense_key, language=LANGUAGE):
    cur = conn.execute(
        "select * from translations where sense_key = ? and language = ? "
        "order by translation_id", (sense_key, language))
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def leaves(rows):
    superseded = {r["supersedes_id"] for r in rows if r.get("supersedes_id") is not None}
    return [r for r in rows if r["translation_id"] not in superseded]


def chains(rows):
    """Group rows into supersession chains, oldest first."""
    by_id = {r["translation_id"]: r for r in rows}
    roots = [r for r in rows if not r.get("supersedes_id") or r["supersedes_id"] not in by_id]
    out = []
    for root in roots:
        chain, cur, guard = [root], root, 0
        while True:
            nxt = [r for r in rows if r.get("supersedes_id") == cur["translation_id"]]
            if not nxt:
                break
            cur = nxt[0]
            chain.append(cur)
            guard += 1
            if guard > len(rows):                     # broken data, stop rather than loop
                break
        out.append(chain)
    return out


def detect_cycles(rows):
    """Return the ids that form a loop. Ids are monotonic so a real insert
    cannot build one; this exists to catch imported or hand-edited data."""
    seen_ids = {r["translation_id"] for r in rows}
    bad = []
    for r in rows:
        seen, cur, steps = set(), r, 0
        while cur.get("supersedes_id") is not None:
            if cur["supersedes_id"] in seen or steps > len(rows):
                bad.append(r["translation_id"])
                break
            seen.add(cur["translation_id"])
            parent = next((x for x in rows if x["translation_id"] == cur["supersedes_id"]), None)
            if parent is None or parent["translation_id"] not in seen_ids:
                break
            cur, steps = parent, steps + 1
    return sorted(set(bad))


def resolve_values(dictionary_text=None, governance=None, has_successor=False):
    """Database-free form of the rule, shared with the Flutter golden file.

    ``governance`` is the active row as a mapping (``text``, ``publication_status``
    and the derivation dimensions). Returns ``text/source/status/visible/
    attribution`` — the same keys ``shared/translation_resolution_golden.json``
    asserts, so both sides test one contract.
    """
    legacy = (dictionary_text or "").strip()
    gov = governance or {}
    gov_text = (gov.get("text") or "").strip()

    if (gov.get("publication_status") or "labeled") == "quarantined":
        derived = status.derive({"publication_status": "quarantined"})
        return {"text": "", "source": "none", "status": derived["code"],
                "visible": False, "attribution": None}

    if has_successor or not gov_text:
        derived = status.derive({})
        return {"text": legacy, "source": "dictionary", "status": derived["code"],
                "visible": bool(legacy), "attribution": None}

    derived = status.derive(gov)
    same_meaning = gov_text == legacy
    return {
        "text": gov_text,
        "source": "dictionary" if same_meaning else "governance",
        "status": derived["code"],
        "visible": derived["visible"] and bool(gov_text),
        "attribution": derived["attribution"],
    }


def resolve(dictionary_text=None, governance=None, has_successor=None):
    """The policy: given the dictionary value and the active governance row, return
    the one meaning the UI shows. Tests and golden vectors use this; the
    store-backed version is :func:`resolve_sense`."""
    if has_successor is None:
        has_successor = bool((governance or {}).get("has_successor"))
    return resolve_values(dictionary_text=dictionary_text, governance=governance,
                          has_successor=has_successor)


def resolve_sense(conn, sense_key, legacy_text=None, language=LANGUAGE):
    """Return the one meaning to display for ``sense_key`` plus its status."""
    rows = _rows(conn, sense_key, language)
    live = [r for r in leaves(rows) if (r.get("publication_status") or "labeled") != "quarantined"]

    chosen, origin = None, "store"
    if live:
        verified = [r for r in live if r.get("human_verification") == "verified"]
        chosen = max(verified or live, key=lambda r: r["translation_id"])
    elif rows:
        # Every row for this sense is quarantined. Quarantine is a decision about
        # *this sense's value*, so the dictionary original is not shown either —
        # otherwise hiding it would be purely cosmetic.
        origin = "quarantined"
    elif (legacy_text or "").strip():
        origin = "dictionary"
        chosen = {"text": legacy_text, "generation_method": "legacy_unknown",
                  "evidence_strength": "none", "validation_status": "incomplete",
                  "publication_status": "labeled", "human_verification": "not_verified",
                  "origin_source": "dictionary.sqlite:senses.ne"}

    if chosen is None:
        return {"sense_key": sense_key, "text": None, "visible": False, "origin": "none",
                "status": None, "attribution": None, "history": []}

    derived = status.derive(chosen)
    return {
        "sense_key": sense_key,
        "text": chosen["text"],
        "visible": derived["visible"],
        "origin": origin,
        "status": derived,
        "attribution": derived["attribution"],
        "translation_id": chosen.get("translation_id"),
        "history": [
            {"translation_id": r["translation_id"], "text": r["text"],
             "publication_status": r.get("publication_status"),
             "human_verification": r.get("human_verification"),
             "supersedes_id": r.get("supersedes_id")}
            for r in rows if r["translation_id"] != chosen.get("translation_id")
        ],
        "chains": chains(rows),
        "cycles": detect_cycles(rows),
    }


def resolve_reference(conn, translation_id, policy="active"):
    """Turn a stored translation id into what the UI should open.

    ``policy='active'`` (default) follows the chain to its active leaf and
    reports the historical id too; ``policy='pinned'`` keeps the referenced row.
    User data is never rewritten — this is a read-time answer.
    """
    row = conn.execute(
        "select * from translations where translation_id = ?", (translation_id,)).fetchone()
    if row is None:
        return {"requested_id": translation_id, "active_id": None, "found": False,
                "policy": policy}
    columns = [d[0] for d in conn.execute(
        "select * from translations where translation_id = ?", (translation_id,)).description]
    record = dict(zip(columns, row))
    rows = _rows(conn, record["sense_key"], record["language"])
    chain = next((c for c in chains(rows)
                  if any(r["translation_id"] == translation_id for r in c)), [record])
    leaf = chain[-1]
    target = translation_id if policy == "pinned" else leaf["translation_id"]
    return {"requested_id": translation_id, "active_id": target, "found": True,
            "policy": policy, "sense_key": record["sense_key"],
            "chain": [r["translation_id"] for r in chain],
            "requested_is_active": target == translation_id}


def integrity_report(conn):
    """Structural checks a pipeline can fail closed on."""
    conn.execute("begin")
    try:
        rows = conn.execute("select translation_id, sense_key, language, supersedes_id, "
                            "human_verification, publication_status from translations").fetchall()
    finally:
        conn.execute("commit")
    recs = [{"translation_id": r[0], "sense_key": r[1], "language": r[2],
             "supersedes_id": r[3], "human_verification": r[4], "publication_status": r[5]}
            for r in rows]
    cycles = detect_cycles(recs)
    branches = {}
    for r in recs:
        if r["supersedes_id"] is not None:
            branches.setdefault(r["supersedes_id"], []).append(r["translation_id"])
    return {"rows": len(recs), "cycles": cycles,
            "branched_parents": {k: v for k, v in branches.items() if len(v) > 1},
            "ok": not cycles and not any(len(v) > 1 for v in branches.values())}
