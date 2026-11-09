"""Rebuild `assets/data/dictionary.sqlite.gz` deterministically.

mtime=0 and a fixed inner filename keep the gzip byte-identical for identical
input, so a rebuild does not look like a data change to git or to the app.
"""

import gzip
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "build" / "dictionary.sqlite"
DST = ROOT.parent / "assets" / "data" / "dictionary.sqlite.gz"


def main() -> int:
    data = SRC.read_bytes()
    print(f"src  {SRC.stat().st_size / 1048576:.2f} MB")
    DST.parent.mkdir(parents=True, exist_ok=True)
    with open(DST, "wb") as raw, gzip.GzipFile(
        filename="dictionary.sqlite", mode="wb", fileobj=raw, mtime=0
    ) as gz:
        gz.write(data)
    print(f"gz   {DST.stat().st_size / 1048576:.2f} MB -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
