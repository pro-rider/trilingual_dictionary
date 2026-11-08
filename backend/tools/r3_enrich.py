"""R3 — enrich only missing or incomplete vocabulary with a controlled AI pass.

Input is the R2 candidate staging file. Only ``new``, ``sense_candidate`` and
``needs_review`` candidates are sent: an exact duplicate with complete verified
senses is never sent to a model, and nothing already in the dictionary is
overwritten. Results are records, not database writes.

Batches are capped at 30 headwords and the model sees short keys (``k1``…),
because long literal keys get rewritten and rows disappear silently.

Outputs (``--out data/r3``):
  enrichments.jsonl   one record per candidate, R3 schema
  rejected.jsonl      model said "not a lexical item" / malformed record
  enrich_report.md    counts, pass rate, malformed records

Usage:
  .venv\\Scripts\\python.exe tools\\r3_enrich.py --candidates data\\r2\\candidates.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ai import provider  # noqa: E402

ELIGIBLE = {"new", "sense_candidate", "needs_review"}
ALLOWED_POS = {"noun", "verb", "adjective", "adverb", "measure_word",
               "name", "phrase", "other"}
ALLOWED_TYPE = {"word", "phrase", "chengyu", "proper_noun", "measure_word", "term"}


def validate(rec: dict) -> list[str]:
    problems = []
    if not rec.get("pinyin"):
        problems.append("missing pinyin")
    if rec.get("pos") and rec["pos"] not in ALLOWED_POS:
        problems.append(f"pos '{rec['pos']}' outside the schema")
    if rec.get("entry_type") and rec["entry_type"] not in ALLOWED_TYPE:
        problems.append(f"entry_type '{rec['entry_type']}' outside the schema")
    if not rec.get("senses"):
        problems.append("no senses")
    for i, s in enumerate(rec.get("senses") or [], start=1):
        if not s.get("en"):
            problems.append(f"sense {i} has no english meaning")
        if len(s.get("en", "")) > 120:
            problems.append(f"sense {i} english meaning is suspiciously long")
    if rec.get("confidence") not in ("high", "medium", "low"):
        problems.append("confidence missing")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default=str(Path("data") / "r2" / "candidates.jsonl"))
    ap.add_argument("--out", default=str(Path("data") / "r3"))
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--attempts", type=int, default=3,
                    help="passes over the pending queue; providers throttle hard "
                         "on bursty use, so failed batches are retried later")
    ap.add_argument("--retry-wait", type=int, default=60)
    ap.add_argument("--chunk-backoff", type=int, default=40)
    ap.add_argument("--chunk-pause", type=float, default=1.5)
    args = ap.parse_args()

    cand_path, out_dir = Path(args.candidates), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cands = [json.loads(l) for l in cand_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    todo = [c for c in cands if c["status"] in ELIGIBLE]
    if args.limit:
        todo = todo[: args.limit]
    print(f"candidates: {len(cands):,} · eligible for enrichment: {len(todo):,} "
          f"(skipped {len(cands) - len(todo):,} exact duplicates)", flush=True)

    done: list[dict] = []
    rejected: list[dict] = []
    malformed: list[dict] = []
    pending: list[dict] = []
    started = time.time()

    attempt = 0
    queue = todo
    while queue and attempt < args.attempts:
        attempt += 1
        pending = []
        for start in range(0, len(queue), args.batch):
            chunk = queue[start:start + args.batch]
            keys = {f"k{i}": c for i, c in enumerate(chunk, start=1)}
            items = []
            for key, c in keys.items():
                existing = ("senses exist, missing data" if c["status"] == "partial"
                            else c["source_gloss"] or "-")
                items.append((key, c["headword"], c.get("context_sentence", ""),
                              ",".join(c["categories"]), existing))
            result = provider.enrich_candidates_batch(items)
            if not result:
                # one failed call opens the circuit breaker for the whole chain;
                # hammering it just keeps every provider closed
                time.sleep(args.chunk_backoff)
            else:
                time.sleep(args.chunk_pause)
            for key, c in keys.items():
                rec = result.get(key)
                if not rec:
                    pending.append(c)
                    continue
                if not rec.get("is_word"):
                    rejected.append({"headword": c["headword"],
                                     "reason": "model: not a lexical item",
                                     "candidate_status": c["status"]})
                    continue
                problems = validate(rec)
                if problems:
                    malformed.append({"headword": c["headword"],
                                      "problems": problems, "raw": rec})
                    continue
                done.append({
                    "headword": c["headword"],
                    "canonical_id": c["canonical_id"],
                    "candidate_status": c["status"],
                    "simplified": c["headword"],
                    "traditional": None,
                    "pinyin": rec["pinyin"],
                    "part_of_speech": rec["pos"] or None,
                    "entry_type": rec["entry_type"] or c["entry_type"],
                    "senses": [{"sense_number": i, "english_meanings": s["en"],
                                "context_sentence": s.get("context") or None,
                                "domain_ids": s.get("domain_ids") or c["categories"],
                                "is_new_sense": c["status"] == "sense_candidate"}
                               for i, s in enumerate(rec["senses"], start=1)],
                    "domain_ids": c["categories"],
                    "specialization_level": rec.get("specialization") or "general",
                    "confidence": rec["confidence"],
                    "confidence_reason": rec.get("confidence_reason") or "",
                    "enrichment_status": "partial" if c["status"] == "partial" else "complete",
                    "source_gloss": c.get("source_gloss"),
                    "source_sha256": c.get("source_sha256"),
                    "extraction_method": c["extraction_method"],
                    "batch_id": f"r3-{attempt}-{start // args.batch:04d}",
                    "model": "failover-chain",
                    "enriched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                })
            el = time.time() - started
            rate = len(done) / max(el, 1)
            print(f"  pass {attempt}  {min(start + args.batch, len(queue)):>5}/{len(queue)}  "
                  f"ok {len(done):>4}  rejected {len(rejected):>3}  "
                  f"pending {len(pending):>3}  {rate:.2f} items/s", flush=True)
        queue = pending
        if queue and attempt < args.attempts:
            print(f"  {len(queue)} left, waiting {args.retry_wait}s for quota to recover "
                  f"(pass {attempt + 1}/{args.attempts})", flush=True)
            time.sleep(args.retry_wait)
    pending = queue

    with (out_dir / "enrichments.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in done:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / "rejected.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in rejected:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / "malformed.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in malformed:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (out_dir / "pending.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in pending:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {
        "eligible": len(todo),
        "enriched": len(done),
        "rejected_not_a_word": len(rejected),
        "malformed": len(malformed),
        "pending_retry": len(pending),
        "senses_produced": sum(len(r["senses"]) for r in done),
        "confidence": dict(Counter(r["confidence"] for r in done)),
        "specialization": dict(Counter(r["specialization_level"] for r in done)),
        "elapsed_s": round(time.time() - started, 1),
    }
    (out_dir / "enrich_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# R3 enrichment report", "",
          f"- eligible candidates: {summary['eligible']:,}",
          f"- enriched: {summary['enriched']:,}",
          f"- model rejected as not-a-word: {summary['rejected_not_a_word']:,}",
          f"- malformed records: {summary['malformed']:,}",
          f"- pending (retry later): {summary['pending_retry']:,}",
          f"- senses produced: {summary['senses_produced']:,}",
          "", "## Confidence", "", "| level | count |", "|---|---:|"]
    for k, v in Counter(r["confidence"] for r in done).most_common():
        md.append(f"| {k} | {v:,} |")
    (out_dir / "enrich_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
