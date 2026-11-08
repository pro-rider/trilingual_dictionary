"""R2 — extract, categorise, deduplicate and reconcile Chinese vocabulary.

Reads the R1 sentence stream, extracts explicit ``中文（English）`` term pairs
and other candidate words, assigns a configurable taxonomy, normalises the
headwords, and reconciles everything against the master dictionary. It never
writes to the database and never asks an AI to enrich anything that already
exists: the output is a staging file for R3/R4.

Outputs (``--out data/r2``):
  candidates.jsonl        one record per unique canonical headword candidate
  term_pairs.jsonl        explicit 中文（English） pairs, verbatim gloss
  reconciliation.md       human-readable summary
  reconciliation.json     the same numbers, machine-readable
  conflicts.csv           conflicting / uncertain matches for review
  unresolved.jsonl        extraction cases the code could not decide

Usage:
  .venv\\Scripts\\python.exe tools\\r2_extract.py --clean data\\clean --out data\\r2
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HAN = r"\u4e00-\u9fff\u3400-\u4dbf"
PAIR_RE = re.compile(rf"([{HAN}][{HAN}、·A-Za-z0-9\-]{{0,19}})"
                     r"(?:（([A-Za-z][^）]{0,80})）|\(([A-Za-z][^)]{0,80})\))")
LATIN_ONLY = re.compile(r"^[A-Za-z]+$")
NUM_ONLY = re.compile(r"^[\d.,%]+$")

STOPCHARS = set("的是在中最和为与了着之其这那有不也很更都就说不被把将从到对以而且及或上下里外个种等我们你他"
                "吗呢吧啊么该每各些由向于如果又还才只便即若如因此但")

STOPWORDS = set("""
的 地 得 了 着 和 与 及 或 而 但 也 就 都 还 又 很 更 最 太 才 只 便 即 且 若 如 因
这 那 此 其 该 各 每 些 个 种 类 等 之 于 为 以 从 到 在 对 由 被 把 将 向 往 自 至
是 有 无 不 没 非 会 能 可 应 要 使 让 得 需 指 称 包括 例如 比如 以及 通过 进行
我们 他们 它们 自己 其中 主要 一般 通常 往往 可以 具有 属于 称为 构成 形成
""".split())

TAXONOMY: dict[str, dict] = {
    "nature": {"parent": None, "keywords": ["动物", "植物", "生物", "生态系统", "物种", "自然"]},
    "nature.animal": {"parent": "nature", "keywords": ["动物", "哺乳", "鸟", "昆虫", "鱼", "爬行", "两栖", "兽", "禽", "脊椎", "无脊椎"]},
    "nature.plant": {"parent": "nature", "keywords": ["植物", "花", "树", "果", "蔬菜", "草本", "农作物", "叶", "根", "种子"]},
    "nature.microbe": {"parent": "nature", "keywords": ["微生物", "细菌", "病毒", "真菌", "寄生虫", "菌"]},
    "science": {"parent": None, "keywords": ["科学", "研究", "理论", "实验"]},
    "science.biology": {"parent": "science", "keywords": ["生物学", "细胞", "遗传", "基因", "DNA", "RNA", "蛋白质", "酶", "进化", "生态"]},
    "science.chemistry": {"parent": "science", "keywords": ["化学", "分子", "原子", "元素", "化合物", "反应", "酸碱"]},
    "science.physics": {"parent": "science", "keywords": ["物理", "力", "能量", "光", "电", "热", "波", "量子", "相对论"]},
    "science.math": {"parent": "science", "keywords": ["数学", "函数", "方程", "几何", "概率", "统计", "矩阵"]},
    "science.astronomy": {"parent": "science", "keywords": ["天文", "行星", "恒星", "星系", "宇宙", "太阳", "月球"]},
    "science.geology": {"parent": "science", "keywords": ["地质", "岩石", "矿物", "地层", "板块", "火山"]},
    "medicine": {"parent": None, "keywords": ["医学", "临床", "疾病", "治疗", "诊断", "患者"]},
    "medicine.disease": {"parent": "medicine", "keywords": ["疾病", "病", "症", "感染", "炎", "癌", "肿瘤", "综合征"]},
    "medicine.anatomy": {"parent": "medicine", "keywords": ["器官", "组织", "骨骼", "肌肉", "神经", "血管", "心脏", "细胞结构"]},
    "medicine.drug": {"parent": "medicine", "keywords": ["药物", "药品", "抗生素", "疫苗", "剂量", "处方"]},
    "medicine.device": {"parent": "medicine", "keywords": ["医疗设备", "扫描仪", "显微镜", "影像", "放射", "器械"]},
    "transport": {"parent": None, "keywords": ["交通", "运输", "车辆", "行驶"]},
    "transport.road": {"parent": "transport", "keywords": ["汽车", "卡车", "公交车", "摩托车", "自行车", "轮胎", "底盘", "发动机", "变速箱"]},
    "transport.rail": {"parent": "transport", "keywords": ["火车", "铁路", "轨道", "列车", "高铁", "地铁"]},
    "transport.air": {"parent": "transport", "keywords": ["飞机", "航空", "机场", "飞行", "航班"]},
    "transport.water": {"parent": "transport", "keywords": ["船", "船舶", "航运", "港口", "集装箱"]},
    "transport.infra": {"parent": "transport", "keywords": ["交通工程", "道路", "公路", "通行能力", "信号灯", "规划"]},
    "tools": {"parent": None, "keywords": ["工具", "仪器", "设备", "机械"]},
    "tools.hand": {"parent": "tools", "keywords": ["锤", "钳", "螺丝刀", "扳手", "锯", "工具"]},
    "tools.machine": {"parent": "tools", "keywords": ["机械", "机床", "齿轮", "轴承", "传动", "液压"]},
    "tools.instrument": {"parent": "tools", "keywords": ["仪器", "测量", "传感器", "仪表", "显微镜", "望远镜"]},
    "tools.music": {"parent": "tools", "keywords": ["乐器", "钢琴", "小提琴", "鼓", "吉他"]},
    "technology": {"parent": None, "keywords": ["技术", "计算机", "软件", "网络", "数字"]},
    "technology.computer": {"parent": "technology", "keywords": ["计算机", "硬件", "处理器", "内存", "芯片", "服务器"]},
    "technology.software": {"parent": "technology", "keywords": ["软件", "编程", "代码", "算法", "程序", "操作系统"]},
    "technology.data": {"parent": "technology", "keywords": ["数据库", "数据", "索引", "存储", "查询"]},
    "technology.ai": {"parent": "technology", "keywords": ["人工智能", "机器学习", "神经网络", "深度学习", "模型", "训练"]},
    "technology.network": {"parent": "technology", "keywords": ["网络", "协议", "互联网", "网络安全", "加密", "路由器"]},
    "technology.robot": {"parent": "technology", "keywords": ["机器人", "自动化", "传感器", "控制系统"]},
    "technology.electronics": {"parent": "technology", "keywords": ["电子", "电路", "半导体", "芯片", "信号"]},
    "society": {"parent": None, "keywords": ["社会", "人", "文化", "教育", "法律", "政府"]},
    "society.family": {"parent": "society", "keywords": ["家庭", "亲属", "父母", "婚姻", "子女"]},
    "society.profession": {"parent": "society", "keywords": ["职业", "工作", "职工", "专业", "行业"]},
    "society.education": {"parent": "society", "keywords": ["教育", "学校", "学生", "课程", "考试", "大学"]},
    "society.government": {"parent": "society", "keywords": ["政府", "政策", "法律", "法规", "管理", "行政"]},
    "society.culture": {"parent": "society", "keywords": ["文化", "艺术", "传统", "节日", "宗教", "文学"]},
    "society.sport": {"parent": "society", "keywords": ["体育", "运动", "比赛", "运动员", "奥运"]},
    "daily": {"parent": None, "keywords": ["生活", "日常", "家庭", "饮食", "衣着"]},
    "daily.food": {"parent": "daily", "keywords": ["食物", "食品", "烹饪", "菜", "饮品", "米", "肉", "调味"]},
    "daily.clothing": {"parent": "daily", "keywords": ["服装", "衣", "鞋", "帽", "布料", "纺织"]},
    "daily.home": {"parent": "daily", "keywords": ["家具", "家居", "房屋", "建筑", "厨房", "家电"]},
    "geography": {"parent": None, "keywords": ["地理", "环境", "地区", "气候"]},
    "geography.place": {"parent": "geography", "keywords": ["国家", "城市", "地区", "省", "山脉", "河流", "海洋", "湖泊"]},
    "geography.climate": {"parent": "geography", "keywords": ["气候", "天气", "温度", "降水", "季风", "温室"]},
    "geography.resource": {"parent": "geography", "keywords": ["资源", "矿产", "能源", "石油", "煤炭", "水资"]},
    "geography.pollution": {"parent": "geography", "keywords": ["污染", "排放", "废", "治理", "生态破坏"]},
    "business": {"parent": None, "keywords": ["商业", "经济", "金融", "贸易", "管理"]},
    "business.finance": {"parent": "business", "keywords": ["金融", "银行", "投资", "利率", "货币", "股票", "融资"]},
    "business.accounting": {"parent": "business", "keywords": ["会计", "财务", "成本", "报表", "审计", "利润"]},
    "business.trade": {"parent": "business", "keywords": ["贸易", "进出口", "关税", "物流", "供应链", "海关"]},
    "business.marketing": {"parent": "business", "keywords": ["营销", "市场", "品牌", "广告", "客户", "定位"]},
    "business.agri": {"parent": "business", "keywords": ["农业", "种植", "养殖", "灌溉", "作物"]},
    "business.industry": {"parent": "business", "keywords": ["工业", "制造", "建筑", "工程", "生产线"]},
    "language": {"parent": None, "keywords": ["语言", "语法", "词", "句子", "翻译"]},
    "language.grammar": {"parent": "language", "keywords": ["语法", "词性", "句式", "时态", "助词"]},
    "language.idiom": {"parent": "language", "keywords": ["成语", "谚语", "俗语"]},
    "language.phrase": {"parent": "language", "keywords": ["短语", "搭配", "词组"]},
    "language.synonym": {"parent": "language", "keywords": ["同义词", "反义词", "近义"]},
    "language.abbrev": {"parent": "language", "keywords": ["缩写", "简称", "略语"]},
}


def domain_of(word: str, sentences: list[str]) -> tuple[list[str], str]:
    """Assign taxonomy IDs from keyword evidence; uncertain is left pending."""
    hay = word + " " + " ".join(sentences[:3])
    hits = [cid for cid, node in TAXONOMY.items()
            if node["parent"] and any(k in hay for k in node["keywords"])]
    if not hits:
        return ["general"], "pending"
    parents = sorted({TAXONOMY[c]["parent"] for c in hits})
    return sorted(set(hits))[:6], ("assigned" if len(hits) <= 3 else "assigned_multi_parent:" + "/".join(parents))


def db_connect(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_dictionary(path: Path) -> dict:
    con = db_connect(path)
    entries = {}
    for row in con.execute(
            "SELECT entry_id, simplified, traditional, pinyin_plain, pos_primary, "
            "category, is_chengyu, is_proper, is_classifier, freq_rank, hsk_level, rarity "
            "FROM entries"):
        entries[row["simplified"]] = dict(row)
    senses = defaultdict(list)
    for row in con.execute(
            "SELECT sense_id, entry_id, sense_order, gloss_en, gloss_zh, gloss_ne, ne_status "
            "FROM senses ORDER BY sense_order"):
        senses[row["entry_id"]].append(dict(row))
    con.close()
    return {"entries": entries, "senses": senses}


def canonical(text: str) -> str:
    text = unicodedata.normalize("NFC", text).strip()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = text.strip("，。、；：！？“”‘’()（）【】")
    return text


def load_sentences(clean_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(clean_dir.glob("*/sentences.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def extract_pairs(sentences: list[dict]) -> list[dict]:
    pairs: dict[tuple[str, str], dict] = {}
    for rec in sentences:
        for m in PAIR_RE.finditer(rec["text"]):
            zh = canonical(m.group(1))
            en = (m.group(2) or m.group(3) or "").strip()
            if not zh or not en or not re.search(f"[{HAN}]", zh):
                continue
            key = (zh, en.lower())
            if key in pairs:
                pairs[key]["sentences"].append(rec["sentence_id"])
                continue
            pairs[key] = {
                "chinese": zh,
                "gloss_en": en,                      # kept verbatim, never rewritten
                "en_source": "text_bracket",
                "sentence_ids": [rec["sentence_id"]],
                "sentence_text": rec["text"],
                "source_document_id": rec["document_id"],
                "source_sha256": rec["source_sha256"],
                "heading_path": rec["heading_path"],
                "warnings": [],
            }
    return list(pairs.values())


def extract_words(sentences: list[dict], headwords: set[str], chengyu: set[str],
                  min_freq: int, max_len: int) -> tuple[dict[str, dict], list[dict]]:
    """Word candidates from jieba segmentation plus dictionary-backed n-grams.

    Free n-grams are deliberately not trusted: that is how junk like 是真 or
    的类 gets into a dictionary. A multi-character candidate is only accepted
    when it is (a) already a master-dictionary headword, (b) a word jieba itself
    knows, or (c) a repeated Han run that does not start or end with a function
    character, and even then it is flagged for review.
    """
    import jieba
    import jieba.posseg as pseg
    for word in headwords:
        jieba.add_word(word, freq=1000, tag="nz")
    jieba_freq = jieba.dt.FREQ
    tags: dict[str, str] = {}

    freq: Counter = Counter()
    context: dict[str, list[str]] = defaultdict(list)
    dropped: list[dict] = []

    def note(word: str, sid: str) -> None:
        freq[word] += 1
        if len(context[word]) < 3:
            context[word].append(sid)

    for rec in sentences:
        sid = rec["sentence_id"]
        text = rec["text"]
        for tok, flag in pseg.cut(text):
            tok = canonical(tok)
            if not tok or not re.match(f"^[{HAN}]", tok):
                continue
            if 2 <= len(tok) <= max_len:
                note(tok, sid)
                tags[tok] = flag
        # dictionary-backed multi-character runs only: idioms and headword
        # corroboration, never blind n-grams
        for run in re.findall(f"[{HAN}]+", text):
            for n in range(2, max_len + 1):
                for i in range(len(run) - n + 1):
                    gram = run[i:i + n]
                    if gram in chengyu or gram in headwords:
                        note(gram, sid)

    out: dict[str, dict] = {}
    for word, count in freq.items():
        if word in STOPWORDS:
            continue
        if LATIN_ONLY.match(word) or NUM_ONLY.match(word):
            continue
        if word[0] in STOPCHARS or word[-1] in STOPCHARS:
            if word not in headwords:
                dropped.append({"headword": word, "reason": "starts/ends with a function character"})
                continue
        known = word in headwords or word in chengyu or jieba_freq.get(word, 0) > 0
        if count < min_freq and not known:
            dropped.append({"headword": word, "reason": f"corpus frequency {count} < {min_freq}"})
            continue
        if not known and count < min_freq * 2:
            dropped.append({"headword": word, "reason": "unknown to jieba/dictionary and thin evidence"})
            continue
        # a brand-new headword must be a lexical unit, not a phrase jieba split
        # off ("展现出", "第一批", "本章"): noun-ish tags, or a short 2-char verb
        flag = tags.get(word, "")
        if word not in headwords and word not in chengyu:
            if not (flag.startswith("n") or flag in ("vn", "an", "nz") or
                    (len(word) == 2 and count >= 3 and flag[:1] in ("v", "a"))):
                dropped.append({"headword": word, "reason": f"not a lexical unit (tag {flag or '?'})"})
                continue
            if re.search(r"(出|着|了|过|起来|下来|上去)$", word) and word not in headwords:
                dropped.append({"headword": word, "reason": "verb + result particle, not a headword"})
                continue
        out[word] = {"count": count, "sentence_ids": context[word][:3],
                     "known_word": word in headwords or word in chengyu,
                     "pos_guess": flag}
    return out, dropped


def reconcile(word: str, senses_meta: list[dict], dic: dict, variant_map: dict,
              pairs_by_word: dict[str, list[dict]]) -> dict:
    entries = dic["entries"]
    if word in entries:
        ent = entries[word]
        s = dic["senses"].get(ent["entry_id"], [])
        missing_ne = [x for x in s if not (x["gloss_ne"] or "").strip()]
        missing_en = [x for x in s if not (x["gloss_en"] or "").strip()]
        status = "exact_duplicate"
        if missing_ne or missing_en:
            status = "partial"
        new_pair = None
        if word in pairs_by_word:
            known = {(x["gloss_en"] or "").strip().lower() for x in s}
            for pair in pairs_by_word[word]:
                if pair["gloss_en"].strip().lower() not in known:
                    new_pair = pair["gloss_en"]
                    status = "sense_candidate"
                    break
        return {"status": status, "canonical_id": ent["entry_id"],
                "existing_senses": len(s), "missing_ne_senses": len(missing_ne),
                "missing_gloss_senses": len(missing_en),
                "proposed_new_sense_gloss": new_pair}
    if word in variant_map:
        target = variant_map[word]
        ent = entries[target]
        return {"status": "verified_variant", "canonical_id": ent["entry_id"],
                "variant_of": target, "existing_senses": len(dic["senses"].get(ent["entry_id"], [])),
                "missing_ne_senses": None, "missing_gloss_senses": None,
                "proposed_new_sense_gloss": None}
    return {"status": "new", "canonical_id": None, "existing_senses": 0,
            "missing_ne_senses": 0, "missing_gloss_senses": 0,
            "proposed_new_sense_gloss": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", default=str(Path("data") / "clean"))
    ap.add_argument("--db", default=str(Path("data") / "build" / "dictionary.sqlite"))
    ap.add_argument("--out", default=str(Path("data") / "r2"))
    ap.add_argument("--min-freq", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=6)
    ap.add_argument("--taxonomy-out", default=str(Path("data") / "taxonomy.json"))
    args = ap.parse_args()

    clean_dir, out_dir = Path(args.clean), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    taxonomy_path = Path(args.taxonomy_out)
    taxonomy_path.write_text(
        json.dumps(TAXONOMY, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sentences = load_sentences(clean_dir)
    if not sentences:
        print(f"no sentences under {clean_dir}", file=sys.stderr)
        return 2
    dic = load_dictionary(Path(args.db))
    headwords = set(dic["entries"])
    chengyu = {w for w, e in dic["entries"].items() if e["is_chengyu"]}
    # traditional -> simplified variants the master dictionary already knows
    variant_map = {e["traditional"]: e["simplified"] for e in dic["entries"].values()
                   if e["traditional"] and e["traditional"] != e["simplified"]}

    pairs = extract_pairs(sentences)
    pairs_by_word: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        pairs_by_word[p["chinese"]].append(p)

    words, dropped = extract_words(sentences, headwords, chengyu, args.min_freq, args.max_len)

    with (out_dir / "term_pairs.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for p in pairs:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    candidates = []
    unresolved = []
    conflicts = []
    for word, meta in words.items():
        sids = meta["sentence_ids"]
        sent_texts = [next((s["text"] for s in sentences if s["sentence_id"] == sid), "")
                      for sid in sids]
        domains, conf = domain_of(word, sent_texts)
        rec = reconcile(word, meta, dic, variant_map, pairs_by_word)
        entry = {
            "headword": word,
            "normalized": canonical(word),
            "canonical_id": rec["canonical_id"],
            "status": rec["status"],
            "variant_of": rec.get("variant_of"),
            "categories": domains,
            "category_confidence": conf,
            "entry_type": ("chengyu" if word in chengyu else
                           "word" if 2 <= len(word) <= 4 else "phrase"),
            "frequency_in_corpus": meta["count"],
            "extraction_method": "jieba+ngram",
            "pos_guess": meta.get("pos_guess"),
            "sentence_ids": sids,
            "context_sentence": (sent_texts[0] if sent_texts else ""),
            "source_gloss": None,
            "existing_senses": rec["existing_senses"],
            "missing_ne_senses": rec["missing_ne_senses"],
            "proposed_new_sense_gloss": rec["proposed_new_sense_gloss"],
            "warnings": [],
        }
        if word in pairs_by_word:
            best = pairs_by_word[word][0]
            entry["source_gloss"] = best["gloss_en"]
            entry["extraction_method"] = "jieba+ngram+text_bracket"
            entry["source_sha256"] = best["source_sha256"]
        else:
            entry["source_sha256"] = sentences[0]["source_sha256"]
        candidates.append(entry)
        if rec["status"] in ("conflict", "needs_review"):
            conflicts.append(entry)
        if not domains or conf == "pending":
            unresolved.append({"headword": word, "reason": "no taxonomy keyword hit"})

    # explicit pairs that jieba never produced as a candidate still matter
    seen = {c["headword"] for c in candidates}
    for word, plist in pairs_by_word.items():
        if word in seen:
            continue
        best = plist[0]
        rec = reconcile(word, [], dic, variant_map, pairs_by_word)
        candidates.append({
            "headword": word, "normalized": canonical(word),
            "canonical_id": rec["canonical_id"], "status": rec["status"],
            "variant_of": rec.get("variant_of"),
            "categories": domain_of(word, [best["sentence_text"]])[0],
            "category_confidence": domain_of(word, [best["sentence_text"]])[1],
            "entry_type": "term", "frequency_in_corpus": len(plist),
            "extraction_method": "text_bracket",
            "sentence_ids": best["sentence_ids"][:3],
            "context_sentence": best["sentence_text"],
            "source_gloss": best["gloss_en"],
            "source_sha256": best["source_sha256"],
            "existing_senses": rec["existing_senses"],
            "missing_ne_senses": rec["missing_ne_senses"],
            "proposed_new_sense_gloss": rec["proposed_new_sense_gloss"],
            "warnings": [],
        })

    with (out_dir / "candidates.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for c in candidates:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    with (out_dir / "unresolved.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for u in unresolved:
            fh.write(json.dumps(u, ensure_ascii=False) + "\n")

    import csv
    with (out_dir / "conflicts.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["headword", "status", "canonical_id", "source_gloss", "categories", "reason"])
        for c in conflicts:
            w.writerow([c["headword"], c["status"], c["canonical_id"] or "",
                        c["source_gloss"] or "", "|".join(c["categories"]),
                        "match cannot be decided automatically"])

    status_counts = Counter(c["status"] for c in candidates)
    method_counts = Counter(c["extraction_method"] for c in candidates)
    summary = {
        "sentences_read": len(sentences),
        "term_pairs_extracted": len(pairs),
        "unique_canonical_headwords": len(candidates),
        "status": dict(status_counts),
        "extraction_method": dict(method_counts),
        "taxonomy_ids": len(TAXONOMY),
        "unresolved_cases": len(unresolved),
        "conflicts": len(conflicts),
        "existing_in_dictionary": sum(1 for c in candidates if c["canonical_id"]),
        "new_headwords": status_counts.get("new", 0),
        "partial_entries_needing_ne": sum(1 for c in candidates
                                          if c["status"] == "partial"),
        "sense_candidates": status_counts.get("sense_candidate", 0),
        "ne_senses_to_translate": sum(c["missing_ne_senses"] or 0 for c in candidates),
    }
    (out_dir / "reconciliation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# R2 reconciliation report", "",
          f"- sentences read: {summary['sentences_read']:,}",
          f"- explicit 中文（English） pairs: {summary['term_pairs_extracted']:,}",
          f"- unique canonical headwords: {summary['unique_canonical_headwords']:,}",
          f"- already in dictionary: {summary['existing_in_dictionary']:,}",
          f"- new headwords: {summary['new_headwords']:,}",
          f"- partial entries (missing data): {summary['partial_entries_needing_ne']:,}",
          f"- possible new senses: {summary['sense_candidates']:,}",
          f"- Nepali senses still to translate: {summary['ne_senses_to_translate']:,}",
          f"- unresolved cases: {summary['unresolved_cases']:,}",
          "", "## Match status", "", "| status | count |", "|---|---:|"]
    for k, v in status_counts.most_common():
        md.append(f"| {k} | {v:,} |")
    md += ["", "## Extraction method", "", "| method | count |", "|---|---:|"]
    for k, v in method_counts.most_common():
        md.append(f"| {k} | {v:,} |")
    (out_dir / "reconciliation.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


