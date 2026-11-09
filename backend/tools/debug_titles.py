import json, sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from build_image_index import WIKIDATA_API, get_json

for w in ["书", "老师", "电脑", "手机", "火车", "声音", "玩具"]:
    data = get_json(WIKIDATA_API, {
        "action": "wbsearchentities", "search": w, "language": "zh",
        "uselang": "zh", "format": "json", "limit": "5", "type": "item",
    })
    print("==", w)
    for hit in data.get("search") or []:
        print("   ", hit.get("id"), "|", hit.get("label"), "|",
              (hit.get("match") or {}).get("type"), "|", (hit.get("description") or "")[:40])
