# Search ranking — the 18 pinned defects

`backend/tests/test_search_ranking.py` has two groups. `CORRECT` (163 cases)
must pass. `KNOWN_DEFECT` (18 cases) marks a wrong answer that is **measured and
reproducible**, with a one-line reason, using `xfail(strict=False)`.

Why pin a bug instead of fixing it:

- The suite stays green, so a real regression is not buried under known noise.
- The defect is executable. When it is fixed the test flips to XPASS and moves
  into `CORRECT` — that is the signal, not a failing build.
- The alternative — widening the matcher until every query "works" — trades a
  visible bug for silent wrong answers elsewhere, which is worse for a learner.

Every expected value was taken from the shipped database via
`tools/_probe_ranking.py`, never from intuition.

## The 18

| query | lang | lands on | why |
|---|---|---|---|
| run | en | 润 | a secondary sense segment scores 85 and ties with the primary 100; banding lets frequency pick 润 |
| beautiful | en | 那 | 55 senses are glossed exactly "beautiful"; 那 carries one as a secondary segment and wins on `sense_order` |
| phone | en | 跑分 | "cell phone" only appears inside a parenthetical in most senses |
| hot | en | 热门 | "hot" is a secondary segment of 热门; 热 is the word meant |
| gou | py | 勾 | tone-less single syllable: 勾 and 狗 share "gou" |
| Nepali | en | (nothing) | no entry is glossed "Nepali"; 尼泊尔语 exists only as a derivative of 尼泊尔 |
| sun | en | 孙 | 孙 carries the exact gloss; 太阳's "sun" is a secondary segment |
| eye | en | 额叶 | "frontal lobe" outranks 眼睛 because 眼睛's gloss is longer and merely contains "eye" |
| heart | en | 中心 | "centre/center" exact gloss beats 心, whose "heart" sense is secondary |
| long | en | 龙 | 龙 "dragon" shares the letters; 长's glosses are "length/long" and lose the exact band |
| hour | en | 后儿 | no sense is glossed "hour"; the winner merely contains the token |
| morning | en | 朝 | 朝 "court/dynasty" carries an archaic "morning" sense, preferred by exact banding |
| arranging | en | 插花 | "flower arranging" contains "arranging"; 安排 is only glossed "arrange" |
| arranged | en | 类书 | "arranged by category" style gloss wins over 安排 for the -ed form |
| teacher | en | 先生 | 先生 "mister" has an exact "teacher" sense; 老师's is secondary |
| problem | en | 难处 | "difficulty" exact gloss outranks 问题 |
| feiji | py | 斐济 | 斐济 "Fiji" and 飞机 both reduce to "feiji"; `is_proper` ordering puts the country first |
| cha | py | 刹 | single tone-less syllable: 刹 "temple" precedes 茶 on frequency |

## What a real fix looks like

1. **Inflection** ("arranging", "arranged") — strip English suffixes before
   matching, and keep the exact band for the base form.
2. **Single tone-less syllable** ("gou", "cha") — when a pinyin query has one
   syllable and many hits, rank by `is_chengyu`/`pos_primary` and by sense count
   rather than raw frequency.
3. **Proper nouns** ("feiji") — `is_proper` should only win when the query looks
   like a name (capitalised Latin input) or when the gloss matches exactly.
4. **Archaic exact matches** ("morning" → 朝, "sun" → 孙) — exact-match banding
   needs a frequency floor: an exact gloss match on a rare entry should not beat
   a secondary match on a frequent one by more than one band.

Each of these touches `app/services/sqlite_dataset.py` scoring, so each needs
its own diff, its own before/after numbers on this suite, and a commit. They are
**not** done in release-prep: the phases' goal is a reviewable release, and a
ranking rewrite is a separate, riskier change.
