# Phase 1 audit — Nepali data quality and coverage

Read-only pass over `C:\Users\Administrator\Desktop\Dictionery\trilingual_dictionary\backend\data\build\dictionary.sqlite` at 2026-11-09T08:25:27+00:00.

## Totals

| Item | Count |
|---|---|
| entries | 123672 |
| senses | 198306 |
| senses_with_ne | 3245 |
| senses_empty_ne | 195061 |
| ne_status_values | 2 |
| examples | 392 |
| images | 77 |

`ne_status` values: `none` 195061, `ai_translated` 3245

## Classification of the 3245 non-empty Nepali values

| Bucket | Count | Share |
|---|---|---|
| ok | 3230 | 99.5% |
| latin_mix | 7 | 0.2% |
| digits | 8 | 0.2% |

Buckets: `ok` = Devanagari only; `latin_mix` = legitimate-looking Nepali with Latin letters (acronyms, units, scientific names) — review, do not reject; `digits` = Devanagari plus numerals; `copy_of_english` = the gloss repeated; `placeholder` = a known non-value; `no_devanagari`/`wrong_script` = cannot be Nepali.

### Examples — latin_mix

| sense_id | word | pinyin | English gloss | Nepali value |
|---|---|---|---|---|
| 5090 | 丙 | bing | letter "C" or Roman "III" in list "A, B, C", or "I, II, III" etc | सूची अक्षर C |
| 49650 | 孔明 | kong ming | courtesy name of Zhuge Liang 諸葛亮|诸葛亮[Zhu1 ge3 Liang4] | Zhuge Liang को सम्मान नाम |
| 59001 | 帅 | shuai | surname Shuai | शuai उपनाम |
| 66092 | 怪不得 | guai bu de | no wonder! | केही आश्चर्य नै हoinu |
| 112935 | 灯 | deng | lamp | बatti |
| 112963 | 灯笼 | deng long | lantern | बatti |
| 170710 | 追求 | zhui qiu | to pursue (a goal etc) stubbornly | दृढतापूर्वक पурсnu |

### Examples — digits

| sense_id | word | pinyin | English gloss | Nepali value |
|---|---|---|---|---|
| 9 | 3D打印 | san d da yin | to 3D print; 3D printing | ३डी प्रिन्ट गर्नु |
| 10 | 3D打印机 | san d da yin ji | 3D printer | ३डी प्रिन्टर |
| 17 | 95后 | jiu wu hou | people born between 1995-01-01 and 1999-12-31 | १९९५ पछिका पुस्ता |
| 19 | 996 | jiu jiu liu | 9am–9pm, six days a week (work schedule) | ९ बजे देखि ९ बजेसम्म, ६ दिन |
| 1555 | 丁 | ding | (archaic) ancient Chinese compass point: 195° | प्राचीन दिशा 195° |
| 4893 | 丑 | chou | ancient Chinese compass point: 30° | ३०° पुरानो दिशा |
| 5091 | 丙 | bing | ancient Chinese compass point: 165° | १६५° पुरानो दिशा |
| 50955 | 宋代 | song dai | Song dynasty (960-1279) | सोंग राजवंश (९६०-१२७९) |

## Coverage by HSK level

| hsk_level | senses | with Nepali | coverage |
|---|---|---|---|
| (null) | 190859 | 508 | 0.3% |
| 5 | 7447 | 2737 | 36.8% |

## Coverage by frequency band

| band | senses | with Nepali | coverage |
|---|---|---|---|
| 1-1000 | 3910 | 775 | 19.8% |
| 1001-5000 | 11618 | 1296 | 11.2% |
| 5001-20000 | 30930 | 839 | 2.7% |
| 20001+ | 142219 | 334 | 0.2% |
| no freq rank | 9629 | 1 | 0.0% |

## Coverage by part of speech

| pos_primary | senses | with Nepali | coverage |
|---|---|---|---|
| (empty) | 198230 | 3169 | 1.6% |
| noun | 40 | 40 | 100.0% |
| verb | 15 | 15 | 100.0% |
| adjective | 12 | 12 | 100.0% |
| other | 4 | 4 | 100.0% |
| adverb | 3 | 3 | 100.0% |
| name | 1 | 1 | 100.0% |
| idom | 1 | 1 | 100.0% |

## Coverage by domain (category, top 12)

| category | senses | with Nepali | coverage |
|---|---|---|---|
| general | 115100 | 2032 | 1.8% |
| everyday | 15328 | 272 | 1.8% |
| people_society | 11780 | 202 | 1.7% |
| transport | 10305 | 160 | 1.6% |
| geography_environment | 10023 | 101 | 1.0% |
| language | 9863 | 89 | 0.9% |
| nature | 7191 | 57 | 0.8% |
| technology | 6411 | 149 | 2.3% |
| business | 5766 | 84 | 1.5% |
| science_medicine | 4715 | 76 | 1.6% |
| tools_instruments | 1824 | 23 | 1.3% |

## Same Nepali word used for different glosses (top 20)

| Nepali (normalised) | glosses it is attached to |
|---|---|
| पुरानो रूप | old variant of 以[yi3], old variant of 卻|却[que4], old variant of 拿[na2], old variant of 深[shen1], old variant of 留[liu2], old variant of 趟[tang1] |
| छोड्नु | to leave, to leave out, to leave; to part (from), to leave; to part from, to relinquish; to abandon, to shed |
| मान्नु | to accept (a suggestion, punishment, bribe etc); to acquiesce, to comply with; to abide by; to respect (an agreement), to like, to obey (an order), to regard as, to treat as |
| विस्तृत | (of an area) vast or extensive, comprehensive, detailed, large, thorough, wide; broad; extensive; widespread |
| मात्र | merely; only; just; nothing but, not only; not just, only, only; merely; just, only; sole |
| बुझ्नु | to comprehend; to understand, to realize; to be aware of; to feel that; to be conscious of (sth relating to oneself), to sense, to understand, to understand; to know about |
| वास्तवमा | actually, actually; in fact; really, in fact, really, really; truly; indeed |
| भिन्न रूप | variant of 岸[an4], variant of 島|岛[dao3], variant of 最[zui4], variant of 碗[wan3] |
| यदि | (coll.) if, if, if; in case; in the event that, so long as; provided; if |
| पहिले नै | before, beforehand; first; earlier, first of all; in the first place, in advance |
| केही | classifier indicating a small amount or small number greater than 1: some, a few, several, few, some, some; certain (things) |
| प्राप्त गर्नु | to obtain; to receive; to get, to receive, to receive (praise, an education, punishment etc); to be ...ed (praised, educated, punished etc), to receive in no small measure |
| काट्नु | clip, to bite, to chop, to harvest |
| थर | family name, surname huo, surname long, surname xian |
| क्षेत्र | field, region, region; area (informal or geographical term), zone |
| मूल | (bound form) root; stem, basic, original, root |
| लगभग | almost, almost; nearly; practically, approximately, roughly |
| विविधता | variant of 櫃檯|柜台[gui4 tai2], variant of 記錄|记录[ji4 lu4], variant of 這裡|这里[zhe4 li3], variant of 遍[bian4] |
| हेर्नु | to look at, to look down upon, to look upon; to regard, to see |
| विषय | subject, subject (of a talk or conversation), subject (under discussion), topic |

## Latin-in-Devanagari samples (needs script review, not rejection)

| word | gloss | Nepali |
|---|---|---|
| 丙 | letter "C" or Roman "III" in list "A, B, C", or "I, II, III" etc | सूची अक्षर C |
| 孔明 | courtesy name of Zhuge Liang 諸葛亮|诸葛亮[Zhu1 ge3 Liang4] | Zhuge Liang को सम्मान नाम |
| 帅 | surname Shuai | शuai उपनाम |
| 怪不得 | no wonder! | केही आश्चर्य नै हoinu |
| 灯 | lamp | बatti |
| 灯笼 | lantern | बatti |
| 追求 | to pursue (a goal etc) stubbornly | दृढतापूर्वक पурсnu |

## Issues, with severity

| severity | issue | count | why it matters |
|---|---|---|---|
| blocker | Missing Nepali gloss | 195061 | Every one of these shows an empty Nepali box in the app |
| review | Latin letters inside a Devanagari value | 7 | Acronyms, units and scientific names are legitimate: review, do not reject |
| review | Same Nepali word used for several different glosses | 40 | Sense-aware termbase must resolve these before reuse |
| blocker | hsk_level is unusable | 7447 | All non-null HSK values are 5, so HSK 1-3 queues are empty |
| blocker | pos_primary is empty | 198230 | No part-of-speech signal, so no concrete-noun or verb filter exists |

