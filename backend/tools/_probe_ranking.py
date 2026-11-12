"""Probe ranking behaviour for the candidate queries below (read-only).

Run from backend/:
    python tools/_probe_ranking.py

It prints the entry the search path actually lands on for each query, so new
regression cases are written from measured behaviour rather than from guesses.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import sqlite_dataset as sd

EN = ["rain", "sun", "moon", "fire", "wind", "snow", "tree", "flower", "fish",
      "bird", "horse", "hand", "head", "eye", "heart", "money", "rice", "tea",
      "coffee", "ticket", "airport", "station", "market", "restaurant", "hotel",
      "teacher", "engineer", "lawyer", "police", "army", "war", "peace",
      "question", "answer", "problem", "important", "difficult", "easy",
      "slow", "fast", "clean", "dirty", "rich", "poor", "young", "old",
      "small", "big", "long", "short", "morning", "evening", "night", "today",
      "tomorrow", "yesterday", "week", "month", "year", "minute", "hour",
      "arranging", "arranged", "nation", "national", "bookcase", "dictionary",
      "Chinese", "English", "Nepali", "Kathmandu", "Lhasa", "Shanghai",
      "Guangzhou", "Shenzhen", "Xi'an"]
ZH = ["雨", "太阳", "月亮", "火", "风", "雪", "树", "花", "鱼", "鸟", "马", "手",
      "头", "眼睛", "心", "钱", "米饭", "茶", "咖啡", "火车", "飞机", "机场",
      "车站", "市场", "学校", "医院", "老师", "警察", "战争", "和平", "问题",
      "答案", "早上", "晚上", "今天", "明天", "昨天", "星期", "分钟", "小时",
      "圖片", "書", "學校", "醫院", "醫生", "電腦", "朋友", "學生", "國"]
PY = ["yu", "taiyang", "yueliang", "huo", "feng", "xue", "shu", "hua", "yu2",
      "niao", "ma", "shou", "tou", "yanjing", "xin", "qian", "mifan", "cha",
      "kafei", "huoche", "feiji", "jichang", "chezhan", "shichang", "xuexiao2",
      "yisheng2", "laoshi", "jingcha", "zhanzheng", "heping", "wenti", "daan",
      "zaoshang", "wanshang", "jintian", "mingtian", "zuotian", "xingqi",
      "fenzhong", "xiaoshi"]


def show(label: str, queries: list[str], lang: str) -> None:
    print(f"\n--- {label} ({lang})")
    for query in queries:
        entry = sd.find_entry(query, lang)
        landed = entry["word_zh"] if entry else None
        print(f"{query!r:>14} -> {landed}")


show("english", EN, "en")
show("chinese", ZH, "zh")
show("pinyin", PY, "py")
