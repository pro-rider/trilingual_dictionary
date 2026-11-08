"""R4 — generate and validate Nepali meanings for R3 senses.

Translation input is the validated **English** gloss, never Chinese: the model
in the chain is an English→Nepali translator, and claiming Chinese→Nepali support
would be an unverified assumption. The Chinese headword and the source sentence
are passed as disambiguating context only.

Every result is stored as ``translation_status=ai_translated`` and
``verification_status=unverified``; nothing becomes verified without a human
review. Back-translation similarity is used as a diagnostic signal only.

Outputs (``--out data/r4``):
  ne_results.jsonl   per sense: nepali, back_en, checks, confidence, review flag
  ne_review.csv      human review queue (medicine/law/finance always included)
  ne_report.md       pass rates by domain band

Usage:
  .venv\\Scripts\\python.exe tools\\r4_ne.py --enriched data\\r3\\enrichments.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ai import provider  # noqa: E402

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LATIN = re.compile(r"[A-Za-z]")
HIGH_IMPACT = {"medicine", "medicine.disease", "medicine.anatomy", "medicine.drug",
               "business.finance", "business.accounting", "society.government"}


def checks(ne: str, back_en: str, gloss: str, zh: str) -> dict:
    out = {}
    out["devanagari_only"] = bool(DEVANAGARI.search(ne)) and not LATIN.search(ne)
    out["not_empty"] = bool(ne.strip())
    out["not_copy_of_english"] = ne.strip().lower() != gloss.strip().lower()
    out["length_ratio"] = round(len(ne) / max(len(gloss), 1), 2)
    out["suspicious_length"] = not (0.2 <= out["length_ratio"] <= 4.0)
    ratio = SequenceMatcher(None, back_en.lower(), gloss.lower()).ratio()
    out["back_translation_similarity"] = round(ratio, 3)
    # 1-2 word glosses ("you", "to be") score badly on string similarity; judge
    # them on term overlap instead of a false negative
    if len(gloss.split()) <= 2:
        out["meaning_ok"] = bool(set(gloss.lower().split()) & set(back_en.lower().split())) \
            or ratio >= 0.5
    else:
        out["meaning_ok"] = ratio >= 0.55
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enriched", default=str(Path("data") / "r3" / "enrichments.jsonl"))
    ap.add_argument("--out", default=str(Path("data") / "r4"))
    ap.add_argument("--batch", type=int, default=15)
    ap.add_argument("--attempts", type=int, default=4)
    ap.add_argument("--retry-wait", type=int, default=90)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = [json.loads(l) for l in Path(args.enriched).read_text(encoding="utf-8").splitlines() if l.strip()]
    flat = []
    for rec in records:
        for s in rec["senses"]:
            flat.append((rec, s))
    print(f"senses to translate: {len(flat):,}", flush=True)

    results: dict[tuple[str, int], dict] = {}
    queue = flat
    attempt = 0
    started = time.time()
    while queue and attempt < args.attempts:
        attempt += 1
        pending = []
        for start in range(0, len(queue), args.batch):
            chunk = queue[start:start + args.batch]
            items = [(f"k{i}", rec["simplified"], s["english_meanings"],
                      s.get("context_sentence") or "")
                     for i, (rec, s) in enumerate(chunk, start=1)]
            got = provider.translate_gloss_queue_batch(items)
            for i, (rec, s) in enumerate(chunk, start=1):
                key = f"k{i}"
                r = got.get(key)
                if not r or not r.get("ne"):
                    pending.append((rec, s))
                    continue
                chk = checks(r["ne"], r.get("back_en", ""), s["english_meanings"], rec["simplified"])
                domain_set = set(rec.get("domain_ids") or [])
                review = (not chk["meaning_ok"] or not chk["devanagari_only"]
                          or chk["suspicious_length"]
                          or bool(domain_set & HIGH_IMPACT)
                          or rec["confidence"] != "high")
                results[(rec["simplified"], s["sense_number"])] = {
                    "canonical_id": rec.get("canonical_id"),
                    "sense_id": None,
                    "word": rec["simplified"],
                    "english_meaning": s["english_meanings"],
                    "nepali_meaning": r["ne"].strip(),
                    "back_en": r.get("back_en", "").strip(),
                    "domain_ids": rec.get("domain_ids"),
                    "translation_model": "failover-chain (groq/gemini/openrouter)",
                    "translation_model_version": "as configured in backend/.env",
                    "termbase_version": "none-yet",
                    "translation_status": "ai_translated",
                    "verification_status": "unverified",
                    "validation_results": chk,
                    "confidence": ("high" if chk["meaning_ok"] and chk["devanagari_only"]
                                   and rec["confidence"] == "high" else
                                   "medium" if chk["meaning_ok"] else "low"),
                    "review_required": review,
                    "review_reason": ("high-impact domain" if bool(domain_set & HIGH_IMPACT)
                                      else "automated check failed" if review else ""),
                    "source_sha256": rec.get("source_sha256"),
                }
            print(f"  pass {attempt}  {min(start + args.batch, len(queue)):>4}/{len(queue)}  "
                  f"done {len(results):>4}  pending {len(pending):>3}", flush=True)
        queue = pending
        if queue and attempt < args.attempts:
            print(f"  {len(queue)} left, waiting {args.retry_wait}s", flush=True)
            time.sleep(args.retry_wait)

    with (out_dir / "ne_results.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in results.values():
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    with (out_dir / "ne_review.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["word", "english_meaning", "nepali_meaning", "back_en",
                    "confidence", "review_required", "review_reason", "domain_ids"])
        for r in results.values():
            if r["review_required"]:
                w.writerow([r["word"], r["english_meaning"], r["nepali_meaning"],
                            r["back_en"], r["confidence"], r["review_required"],
                            r["review_reason"], "|".join(r["domain_ids"] or [])])

    counts = Counter(r["confidence"] for r in results.values())
    review = sum(1 for r in results.values() if r["review_required"])
    summary = {"senses": len(flat), "translated": len(results),
               "failed": len(flat) - len(results), "confidence": dict(counts),
               "review_required": review,
               "devanagari_pass": sum(1 for r in results.values()
                                      if r["validation_results"]["devanagari_only"]),
               "meaning_pass": sum(1 for r in results.values()
                                   if r["validation_results"]["meaning_ok"]),
               "elapsed_s": round(time.time() - started, 1)}
    (out_dir / "ne_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    md = ["# R4 Nepali generation report", "",
          f"- senses queued: {summary['senses']:,}",
          f"- translated: {summary['translated']:,}",
          f"- failed (retry later): {summary['failed']:,}",
          f"- Devanagari-only check passed: {summary['devanagari_pass']:,}",
          f"- meaning (back-translation) passed: {summary['meaning_pass']:,}",
          f"- sent to human review: {summary['review_required']:,}",
          "", "| confidence | count |", "|---|---:|"]
    for k, v in counts.most_common():
        md.append(f"| {k} | {v:,} |")
    (out_dir / "ne_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
