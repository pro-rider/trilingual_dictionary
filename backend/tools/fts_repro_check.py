"""Reproducibility evidence for the FTS rebuild (Gate C).

Compares the two index tables' *content* across independent rebuilds of the
same source copy, proves the entries table is untouched, and proves the
canonical asset was not modified.
"""
import hashlib
import json
import os
import sqlite3
import sys


def digest(path, table, columns):
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    try:
        rows = conn.execute(
            "select %s from %s order by entry_id" % (", ".join(columns), table)).fetchall()
    finally:
        conn.close()
    h = hashlib.sha256()
    for row in rows:
        h.update(("\x1e".join("" if v is None else str(v) for v in row) + "\x1d").encode("utf-8"))
    return h.hexdigest(), len(rows)


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    work = os.environ.get("TEMP", ".")
    src = os.path.join(root, "data", "build", "dictionary.sqlite")
    c1 = os.path.join(work, "rehearsal", "copy1.sqlite")
    c2 = os.path.join(work, "rehearsal", "copy2.sqlite")
    result = {"source_sha_before": file_sha(src), "source_sha_after": None, "copies": {}}
    cols = {
        "entries": ("entry_id", "simplified", "traditional", "pinyin_search", "category", "freq_rank"),
        "fts": ("entry_id", "simplified", "traditional", "pinyin_search", "english", "category"),
        "fts_zh": ("entry_id", "simplified", "traditional", "english"),
    }
    for label, path in (("copy1", c1), ("copy2", c2)):
        result["copies"][label] = {t: digest(path, t, c) for t, c in cols.items()}
    # Prove the rebuild did not touch the dictionary's own rows.
    result["entries_identical_to_source"] = (
        result["copies"]["copy1"]["entries"] == digest(src, "entries", cols["entries"]))
    # Idempotency: a second rebuild of copy1 must land on the same content.
    sys.path.insert(0, os.path.join(root, "backend", "tools"))
    import rebuild_fts
    again = rebuild_fts.rebuild(c1)
    result["second_rebuild_ok"] = again["ok"]
    result["second_rebuild_hashes"] = {t: digest(c1, t, c)
                                      for t, c in cols.items() if t != "entries"}
    result["idempotent"] = (result["second_rebuild_hashes"]["fts"]
                            == result["copies"]["copy1"]["fts"]
                            and result["second_rebuild_hashes"]["fts_zh"]
                            == result["copies"]["copy1"]["fts_zh"])
    # Independent rebuild on a second copy must converge to the same indexes.
    rebuild_fts.rebuild(c2)
    result["copies"]["copy2"] = {t: digest(c2, t, c) for t, c in cols.items()}
    result["reproducible"] = (result["copies"]["copy2"]["fts"] == result["copies"]["copy1"]["fts"]
                              and result["copies"]["copy2"]["fts_zh"]
                              == result["copies"]["copy1"]["fts_zh"])
    result["source_sha_after"] = file_sha(src)
    result["source_unchanged"] = result["source_sha_before"] == result["source_sha_after"]
    result["ok"] = all(result[k] for k in
                       ("entries_identical_to_source", "second_rebuild_ok", "idempotent",
                        "reproducible", "source_unchanged"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
