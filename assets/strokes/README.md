# Stroke data (generated — do not edit)

Built by `tools/build_stroke_pack.py` on 2026-11-15 for the top
3000 words.

- `strokes.bin.gz` — 1835 characters, 5099681 bytes raw
  (2073302 bytes gzipped), sha256 106ffb42715d83af014d284ae096a3e656fc0411319b3812aadb2c5e32fb2205
- `strokes.index.json` — byte offset and length of each character's line, the
  Kangxi radical per character, and the `disputed` list
- `strokes.source_counts.json` — the stroke count the source file gives for each
  character, recorded before packing so a conversion slip cannot pass unnoticed
- `build_info.json` — the same facts for the Credits screen
- `ARPHICPL.TXT` — the licence, unaltered

Source: `hanzi-writer-data@2.0.1` (npm), sha256 of the tarball `72baf3d82b114e60d6e40ea05f24d2262a05cd39d544e2f322ba2fceb7beff15`, derived
from Make Me a Hanzi `graphics.txt`, which came from fonts by Arphic Technology
Co., Ltd.

Conversion: per-character JSON (strokes, medians, radStrokes) reduced to the keys s (stroke outlines), m (stroke medians) and r (radical stroke indices), coordinates rounded to 1 decimal, one JSON object per line, concatenated and gzipped. No character was added, changed or invented.

The converted data is available under the Arphic Public License — see
`docs/LICENSE-ARPHIC.md`.

Words in this band with no full coverage (81): 是 和 和 为 年 说 个 并 以 时 最 只 向 出 却 吃 岁 话 因 叫 乾 干 玩 拿 拿 据 回 期 法 法 线 笑 帮 帮 花 花 面 群 逼 德 德 往 尔 救 克 词 枪 操 深 岛 馆 局 球 视 视 弄 留 留 罪 骂 歌 船 怪 腿 苏 药 射 塔 凭 宝 杯 绝 剑 卽 榦 眞 麫 旣 敎 奬 畵
