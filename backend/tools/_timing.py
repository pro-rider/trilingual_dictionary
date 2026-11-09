import time, sys
sys.path.insert(0, "tools")
import images_v2 as m

for term in ["苹果", "汽车", "月亮"]:
    t0 = time.time()
    c = m.resolve_concept_zh(term)
    t1 = time.time()
    files = m.concept_image_files(c["qid"]) if c else []
    t2 = time.time()
    a = m.file_asset(files[0]) if files else None
    t3 = time.time()
    print(f"{term}: search {t1-t0:.1f}s claims {t2-t1:.1f}s imageinfo {t3-t2:.1f}s "
          f"-> {c and c['qid']} {files[:1]} {a and a.license}")
