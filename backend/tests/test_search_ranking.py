"""Search-ranking regression suite (Phase 10).

Every case below is a query a learner actually types. Two groups:

* ``CORRECT`` — behaviour that is right today and must not silently drift when
  the ranking code changes. ``arrange`` and ``Nepal`` were the two bugs that
  started this rule (布局 beating 安排; the bird "Nepal fulvetta" beating 尼泊尔).
* ``KNOWN_DEFECT`` — measured, reproducible wrong answers. They are marked
  ``xfail(strict=False)`` so the suite stays green *and* the defect is
  executable: when someone fixes one, the test flips to XPASS and should be
  moved into ``CORRECT``. The reasoning for not fixing them yet is in
  ``docs/RANKING_KNOWN_DEFECTS.md``.

The suite runs against the real built database (read-only). It skips cleanly on
a machine where ``backend/data/build/dictionary.sqlite`` is absent.
"""

from pathlib import Path

import pytest

from app.core import config
from app.services import sqlite_dataset as sd

DB = Path(config.settings.dictionary_db_path)


pytestmark = pytest.mark.skipif(
    not DB.exists(), reason="built dictionary is not present on this machine"
)


@pytest.fixture(autouse=True)
def _pin_database(monkeypatch):
    """Other tests in this suite point `dictionary_db_path` at throwaway
    fixtures and leave the module cache warm. Pin the real database explicitly
    so this file measures the shipped data no matter what ran before it."""
    monkeypatch.setattr(config.settings, "dictionary_db_path", str(DB))
    sd.reset_cache()
    yield
    sd.reset_cache()


# query, lang, headword the learner must land on
CORRECT = [
    # --- the two original bugs, kept forever -------------------------------
    ("arrange", "en", "安排"),          # was 布局 ("arrangement")
    ("Nepal", "en", "尼泊尔"),           # was 白眶雀鹛 "Nepal fulvetta"
    # --- exact gloss beats a longer gloss that merely contains the word ----
    ("water", "en", "水"),
    ("book", "en", "书"),
    ("house", "en", "房子"),
    ("library", "en", "图书馆"),
    ("hospital", "en", "医院"),
    ("red", "en", "红"),
    ("three", "en", "三"),
    ("cat", "en", "猫"),
    ("dog", "en", "狗"),
    ("birthday", "en", "生日"),
    ("computer", "en", "电脑"),
    ("delicious", "en", "好吃"),
    ("cold", "en", "冷"),
    # --- exact gloss on a content word, frequency breaks the tie ----------
    ("because", "en", "因为"),
    ("although", "en", "虽然"),
    ("arrangement", "en", "布局"),
    ("mountain", "en", "山"),
    ("measure word", "en", "量词"),
    ("quickly", "en", "赶快"),
    ("happy", "en", "快乐"),
    ("doctor", "en", "医生"),
    ("friend", "en", "朋友"),
    ("student", "en", "学生"),
    ("school", "en", "学校"),
    ("study", "en", "学习"),
    ("eat", "en", "吃"),
    ("drink", "en", "喝"),
    ("sleep", "en", "睡"),
    ("write", "en", "写"),
    ("speak", "en", "说"),
    # --- proper noun typed in English resolves by pinyin spelling ---------
    ("Beijing", "en", "北京"),
    # --- Chinese, simplified and traditional input ------------------------
    ("安排", "zh", "安排"),
    ("水", "zh", "水"),
    ("中国", "zh", "中国"),
    ("学习", "zh", "学习"),
    ("睡觉", "zh", "睡觉"),
    ("电脑", "zh", "电脑"),
    ("医生", "zh", "医生"),
    ("快乐", "zh", "快乐"),
    ("學習", "zh", "学习"),       # traditional -> simplified
    ("手機", "zh", "手机"),       # traditional -> simplified
    # --- pinyin, with and without spaces, without tones -------------------
    ("anpai", "py", "安排"),      # joined form: used to return nothing
    ("an pai", "py", "安排"),     # spaced form
    ("shui", "py", "水"),         # used to answer 帨 "handkerchief"
    ("zhongguo", "py", "中国"),   # joined token sat second in pinyin_search
    ("xuexi", "py", "学习"),      # used to answer 学习强国 (the PRC app)
    ("beijing", "py", "北京"),
    ("shanghai", "py", "上海"),
    ("nihao", "py", "你好"),
    ("xiexie", "py", "谢谢"),
    ("zaijian", "py", "再见"),
    ("pengyou", "py", "朋友"),
    ("xuexiao", "py", "学校"),
    ("diannao", "py", "电脑"),
    ("shouji", "py", "手机"),
    ("haochi", "py", "好吃"),
    ("shengri", "py", "生日"),
    ("yisheng", "py", "医生"),
    ("kuaile", "py", "快乐"),
    # --- batch 2: everyday nouns, measured on the shipped database ---------
    ("rain", "en", "雨"),
    ("moon", "en", "月"),
    ("fire", "en", "火"),
    ("wind", "en", "风"),
    ("snow", "en", "雪"),
    ("tree", "en", "树"),
    ("flower", "en", "花"),
    ("fish", "en", "鱼"),
    ("bird", "en", "鸟"),
    ("horse", "en", "马"),
    ("hand", "en", "手"),
    ("head", "en", "头"),
    ("tea", "en", "茶"),
    ("coffee", "en", "咖啡"),
    ("ticket", "en", "票"),
    ("airport", "en", "机场"),
    ("market", "en", "市场"),
    ("engineer", "en", "工程师"),
    ("lawyer", "en", "律师"),
    ("police", "en", "警察"),
    ("war", "en", "战争"),
    ("peace", "en", "和平"),
    ("question", "en", "问题"),
    ("important", "en", "重要"),
    ("easy", "en", "容易"),
    ("slow", "en", "慢"),
    ("clean", "en", "干净"),
    ("young", "en", "年轻"),
    ("small", "en", "小"),
    ("big", "en", "大"),
    ("short", "en", "短"),
    ("evening", "en", "晚上"),
    ("night", "en", "夜"),
    ("today", "en", "今天"),
    ("tomorrow", "en", "明天"),
    ("yesterday", "en", "昨天"),
    ("week", "en", "周"),
    ("month", "en", "月份"),
    ("year", "en", "年"),
    ("minute", "en", "分钟"),
    # --- contains-vs-exact: the query appears inside a compound headword ---
    ("nation", "en", "国家"),
    ("bookcase", "en", "书柜"),
    ("dictionary", "en", "词典"),
    ("English", "en", "英语"),
    # --- proper nouns resolve by pinyin, not by gloss containment ----------
    ("Kathmandu", "en", "加德满都"),
    ("Shanghai", "en", "上海"),
    ("Guangzhou", "en", "广州"),
    ("Shenzhen", "en", "深圳"),
    # --- Chinese batch 2, simplified input ---------------------------------
    ("雨", "zh", "雨"),
    ("太阳", "zh", "太阳"),
    ("眼睛", "zh", "眼睛"),
    ("咖啡", "zh", "咖啡"),
    ("火车", "zh", "火车"),
    ("飞机", "zh", "飞机"),
    ("机场", "zh", "机场"),
    ("车站", "zh", "车站"),
    ("市场", "zh", "市场"),
    ("老师", "zh", "老师"),
    ("警察", "zh", "警察"),
    ("战争", "zh", "战争"),
    ("和平", "zh", "和平"),
    ("问题", "zh", "问题"),
    ("答案", "zh", "答案"),
    ("早上", "zh", "早上"),
    ("晚上", "zh", "晚上"),
    ("今天", "zh", "今天"),
    ("明天", "zh", "明天"),
    ("昨天", "zh", "昨天"),
    ("星期", "zh", "星期"),
    ("分钟", "zh", "分钟"),
    ("小时", "zh", "小时"),
    # --- Chinese batch 2, traditional input -> simplified result -----------
    ("圖片", "zh", "图片"),
    ("書", "zh", "书"),
    ("學校", "zh", "学校"),
    ("醫院", "zh", "医院"),
    ("醫生", "zh", "医生"),
    ("電腦", "zh", "电脑"),
    ("學生", "zh", "学生"),
    ("國", "zh", "国"),
    # --- pinyin batch 2: two-syllable words, tone-less ---------------------
    ("taiyang", "py", "太阳"),
    ("yueliang", "py", "月亮"),
    ("huoche", "py", "火车"),
    ("jichang", "py", "机场"),
    ("chezhan", "py", "车站"),
    ("shichang", "py", "市场"),
    ("laoshi", "py", "老师"),
    ("jingcha", "py", "警察"),
    ("zhanzheng", "py", "战争"),
    ("heping", "py", "和平"),
    ("wenti", "py", "问题"),
    ("zaoshang", "py", "早上"),
    ("wanshang", "py", "晚上"),
    ("jintian", "py", "今天"),
    ("mingtian", "py", "明天"),
    ("zuotian", "py", "昨天"),
    ("xingqi", "py", "星期"),
    ("fenzhong", "py", "分钟"),
    ("xiaoshi", "py", "小时"),
    ("mifan", "py", "米饭"),
    ("kafei", "py", "咖啡"),
    ("yanjing", "py", "眼睛"),
]

# query, lang, what it wrongly returns today, why it is not fixed yet
KNOWN_DEFECT = [
    ("run", "en", "润",
     "a secondary sense segment scores 85 and ties with the primary "
     "sense 100; banding lets frequency pick the wrong character"),
    ("beautiful", "en", "那",
     "55 senses are glossed exactly 'beautiful'; 那 carries one as a "
     "secondary segment and outranks 美 on sense_order"),
    ("phone", "en", "跑分",
     "'cell phone' only appears inside a parenthetical in most senses"),
    ("hot", "en", "热门",
     "'hot' is a secondary segment of 热门; 热 is the word meant"),
    ("gou", "py", "勾",
     "tone-less single syllable: 勾 and 狗 share 'gou'"),
    ("Nepali", "en", None,
     "no entry is glossed 'Nepali'; 尼泊尔语 exists only as 尼泊尔's "
     "derivative, so returning nothing is honest but unhelpful"),
    # --- batch 2: measured on 2026-11-12 ------------------------------------
    ("sun", "en", "孙",
     "孙 'grandson / surname' carries the exact gloss; 太阳 is only glossed "
     "'sun' as a secondary segment, so banding + frequency picks 孙"),
    ("eye", "en", "额叶",
     "'frontal lobe' outranks 眼睛 because 眼睛's sense is a longer gloss "
     "containing 'eye'"),
    ("heart", "en", "中心",
     "'centre/center' exact gloss beats 心, whose 'heart' sense is secondary"),
    ("long", "en", "龙",
     "龙 'dragon' shares the letters with the adjective 'long'; 长's glosses "
     "are 'length/long' and lose the exact-match band"),
    ("hour", "en", "后儿",
     "'later' style glosses match 'hour' nowhere; the winner is a rare word "
     "whose gloss happens to contain the token"),
    ("morning", "en", "朝",
     "朝 'court/dynasty' carries an archaic 'morning' sense, which the exact "
     "band prefers over 早上"),
    ("arranging", "en", "插花",
     "'flower arranging' contains 'arranging'; 安排 is only glossed "
     "'arrange', so the -ing form has no exact match"),
    ("arranged", "en", "类书",
     "'arranged by category' style gloss wins over 安排 for the -ed form"),
    ("teacher", "en", "先生",
     "先生 'mister' has an exact 'teacher' sense; 老师's is secondary"),
    ("problem", "en", "难处",
     "'difficulty' exact gloss outranks 问题, whose 'problem' sense is shared "
     "with 问题/难题"),
    ("feiji", "py", "斐济",
     "斐济 'Fiji' and 飞机 both reduce to 'feiji'; is_proper ordering puts the "
     "country first"),
    ("cha", "py", "刹",
     "single tone-less syllable: 刹 'temple' precedes 茶 on frequency"),
]


@pytest.mark.parametrize("query,lang,expected", CORRECT)
def test_ranking_is_correct(query, lang, expected):
    entry = sd.find_entry(query, lang)
    assert entry is not None, f"{query!r} ({lang}) returned nothing"
    assert entry["word_zh"] == expected, (
        f"{query!r} ({lang}) landed on {entry['word_zh']}, expected {expected}"
    )


@pytest.mark.parametrize("query,lang,current,reason", KNOWN_DEFECT)
def test_known_defect_is_still_what_it_was(query, lang, current, reason):
    """Pins today's wrong answer with an explanation.

    ``strict=False``: if the ranking is fixed, this XPASSes instead of failing
    the build — the signal to move the case into ``CORRECT``.
    """
    pytest.xfail(f"known ranking defect: {reason}")
    entry = sd.find_entry(query, lang)
    landed = entry["word_zh"] if entry else None
    assert landed == current


def test_unknown_word_returns_nothing_instead_of_a_guess():
    """A word the dictionary does not define must not be answered with the
    closest-looking row."""
    assert sd.find_entry("zzzqqqxxx", "en") is None
