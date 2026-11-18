"""Generate the category illustrations used when no photograph exists.

Roughly half of the dictionary's headwords are verbs, grammar glosses or abstract
concepts, and no image library has a photograph of them. Rather than leave those
rows as an empty frame, every entry belongs to one of eleven categories, so each
category gets one calm, consistent illustration drawn here in code.

Everything is drawn locally with Pillow: no stock photography, no model calls, no
licence to clear, and the output is deterministic (the same input always produces
byte-identical files), which keeps the build reproducible.

Usage:
    python tools/build_category_illustrations.py            # draw + write assets
    python tools/build_category_illustrations.py --register  # also fill the DB

The ``--register`` step writes one row per category into ``images`` and then maps
every entry that still has no image to its category illustration, so the number of
entries with an image reaches the full 123k without inventing photographs.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
SUPERSAMPLE = 2  # draw large, downscale: cheap anti-aliasing on flat shapes

# One muted hue per category, so illustrations read as a family and never clash
# with the UI's dark theme.
CATEGORIES: dict[str, tuple[str, tuple[int, int, int]]] = {
    "general": ("开放书本", (88, 106, 136)),
    "everyday": ("日常器物", (188, 140, 100)),
    "people_society": ("人群", (162, 112, 132)),
    "geography_environment": ("山川", (92, 142, 130)),
    "language": ("语言", (126, 112, 172)),
    "transport": ("交通", (92, 132, 172)),
    "nature": ("自然", (112, 152, 104)),
    "business": ("商业", (172, 132, 92)),
    "technology": ("科技", (100, 122, 152)),
    "science_medicine": ("实验", (142, 122, 162)),
    "tools_instruments": ("工具", (152, 132, 100)),
}

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
)


def _canvas(colour: tuple[int, int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    size = SIZE * SUPERSAMPLE
    background = tuple(int(c * 0.16 + 255 * 0.84) for c in colour)
    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    return image, draw


def _ink(colour: tuple[int, int, int], factor: float = 1.0) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in colour)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def draw_general(draw: ImageDraw.ImageDraw, colour):
    """An open book: two facing pages and a binding shadow."""
    s = SIZE * SUPERSAMPLE
    cy = s // 2
    left = [(s * 0.16, cy - s * 0.18), (s * 0.48, cy - s * 0.24), (s * 0.48, cy + s * 0.20), (s * 0.16, cy + s * 0.14)]
    right = [(s * 0.84, cy - s * 0.18), (s * 0.52, cy - s * 0.24), (s * 0.52, cy + s * 0.20), (s * 0.84, cy + s * 0.14)]
    draw.polygon(left, fill=_ink(colour, 0.95))
    draw.polygon(right, fill=_ink(colour, 1.15))
    draw.line([(s * 0.48, cy - s * 0.24), (s * 0.52, cy - s * 0.24)], fill=_ink(colour, 0.55), width=int(s * 0.012))
    for i in range(3):
        y = cy - s * 0.08 + i * s * 0.10
        draw.line([(s * 0.22, y), (s * 0.42, y + s * 0.02)], fill=_ink(colour, 0.55), width=int(s * 0.010))
        draw.line([(s * 0.58, y + s * 0.02), (s * 0.78, y)], fill=_ink(colour, 0.55), width=int(s * 0.010))


def draw_everyday(draw: ImageDraw.ImageDraw, colour):
    """A cup on a saucer with a steam curl."""
    s = SIZE * SUPERSAMPLE
    cx, cy = s * 0.46, s * 0.58
    draw.rounded_rectangle([cx - s * 0.20, cy - s * 0.16, cx + s * 0.20, cy + s * 0.16],
                           radius=int(s * 0.05), fill=_ink(colour, 1.0))
    draw.ellipse([cx + s * 0.14, cy - s * 0.10, cx + s * 0.30, cy + s * 0.06], outline=_ink(colour, 0.85), width=int(s * 0.014))
    draw.arc([cx - s * 0.06, cy - s * 0.34, cx + s * 0.12, cy - s * 0.14], 120, 440, fill=_ink(colour, 0.6), width=int(s * 0.012))
    draw.rounded_rectangle([cx - s * 0.30, cy + s * 0.18, cx + s * 0.30, cy + s * 0.24],
                           radius=int(s * 0.03), fill=_ink(colour, 0.7))


def draw_people_society(draw: ImageDraw.ImageDraw, colour):
    """Three figures, centre one forward, suggesting a group."""
    s = SIZE * SUPERSAMPLE
    base = s * 0.74
    for dx, scale, shade in ((-s * 0.24, 0.72, 0.70), (s * 0.24, 0.72, 0.70), (0, 1.0, 1.0)):
        cx = s * 0.5 + dx
        r = s * 0.11 * scale
        head_y = base - s * 0.26 * scale
        draw.ellipse([cx - r, head_y - r, cx + r, head_y + r], fill=_ink(colour, shade))
        body_w = r * 1.5
        draw.rounded_rectangle([cx - body_w, head_y + r * 0.9, cx + body_w, base],
                               radius=int(r * 0.6), fill=_ink(colour, shade))


def draw_geography_environment(draw: ImageDraw.ImageDraw, colour):
    """Layered ridges with a river bend and a sun."""
    s = SIZE * SUPERSAMPLE
    draw.ellipse([s * 0.66, s * 0.16, s * 0.82, s * 0.32], fill=_ink(colour, 1.2))
    for pts, shade in (
        ([(s * 0.10, s * 0.70), (s * 0.34, s * 0.34), (s * 0.58, s * 0.70)], 0.75),
        ([(s * 0.30, s * 0.74), (s * 0.58, s * 0.40), (s * 0.88, s * 0.74)], 1.0),
    ):
        draw.polygon(pts, fill=_ink(colour, shade))
    draw.line([(s * 0.12, s * 0.82), (s * 0.38, s * 0.76), (s * 0.62, s * 0.84), (s * 0.88, s * 0.78)],
              fill=_ink(colour, 1.25), width=int(s * 0.018))


def draw_language(draw: ImageDraw.ImageDraw, colour):
    """A speech bubble holding the character 文."""
    s = SIZE * SUPERSAMPLE
    draw.rounded_rectangle([s * 0.16, s * 0.22, s * 0.84, s * 0.66],
                           radius=int(s * 0.10), fill=_ink(colour, 1.0))
    draw.polygon([(s * 0.30, s * 0.66), (s * 0.44, s * 0.66), (s * 0.30, s * 0.80)], fill=_ink(colour, 1.0))
    glyph = _font(int(s * 0.26))
    draw.text((s * 0.5, s * 0.44), "文", font=glyph, fill=(255, 255, 255), anchor="mm")


def draw_transport(draw: ImageDraw.ImageDraw, colour):
    """A bus silhouette with windows and wheels."""
    s = SIZE * SUPERSAMPLE
    draw.rounded_rectangle([s * 0.14, s * 0.36, s * 0.86, s * 0.68],
                           radius=int(s * 0.08), fill=_ink(colour, 1.0))
    for i in range(3):
        x = s * (0.22 + i * 0.20)
        draw.rounded_rectangle([x, s * 0.42, x + s * 0.14, s * 0.54],
                               radius=int(s * 0.03), fill=(255, 255, 255))
    for x in (s * 0.30, s * 0.70):
        draw.ellipse([x - s * 0.08, s * 0.64, x + s * 0.08, s * 0.80], fill=_ink(colour, 0.55))


def draw_nature(draw: ImageDraw.ImageDraw, colour):
    """A leaf with a midrib, plus a low sun."""
    s = SIZE * SUPERSAMPLE
    draw.ellipse([s * 0.62, s * 0.18, s * 0.80, s * 0.36], fill=_ink(colour, 1.2))
    draw.polygon([(s * 0.20, s * 0.80), (s * 0.44, s * 0.28), (s * 0.74, s * 0.70)], fill=_ink(colour, 1.0))
    draw.polygon([(s * 0.20, s * 0.80), (s * 0.44, s * 0.28), (s * 0.46, s * 0.80)], fill=_ink(colour, 0.78))
    draw.line([(s * 0.24, s * 0.78), (s * 0.46, s * 0.32)], fill=_ink(colour, 0.5), width=int(s * 0.010))


def draw_business(draw: ImageDraw.ImageDraw, colour):
    """Three rising bars under an arrow."""
    s = SIZE * SUPERSAMPLE
    base = s * 0.78
    for i, height in enumerate((0.20, 0.32, 0.46)):
        x = s * (0.20 + i * 0.22)
        draw.rounded_rectangle([x, base - s * height, x + s * 0.14, base],
                               radius=int(s * 0.02), fill=_ink(colour, 0.8 + i * 0.12))
    draw.line([(s * 0.24, s * 0.36), (s * 0.62, s * 0.22)], fill=_ink(colour, 1.3), width=int(s * 0.014))
    draw.polygon([(s * 0.62, s * 0.22), (s * 0.54, s * 0.22), (s * 0.61, s * 0.30)], fill=_ink(colour, 1.3))


def draw_technology(draw: ImageDraw.ImageDraw, colour):
    """A processor with pin lines."""
    s = SIZE * SUPERSAMPLE
    draw.rounded_rectangle([s * 0.30, s * 0.30, s * 0.70, s * 0.70],
                           radius=int(s * 0.05), fill=_ink(colour, 1.0))
    draw.rounded_rectangle([s * 0.40, s * 0.40, s * 0.60, s * 0.60],
                           radius=int(s * 0.03), fill=_ink(colour, 0.55))
    for offset in (0.38, 0.50, 0.62):
        y = s * offset
        draw.line([(s * 0.18, y), (s * 0.30, y)], fill=_ink(colour, 0.9), width=int(s * 0.012))
        draw.line([(s * 0.70, y), (s * 0.82, y)], fill=_ink(colour, 0.9), width=int(s * 0.012))


def draw_science_medicine(draw: ImageDraw.ImageDraw, colour):
    """An Erlenmeyer flask with liquid and two bubbles."""
    s = SIZE * SUPERSAMPLE
    draw.polygon([(s * 0.42, s * 0.24), (s * 0.58, s * 0.24), (s * 0.58, s * 0.46),
                  (s * 0.78, s * 0.76), (s * 0.22, s * 0.76), (s * 0.42, s * 0.46)],
                 fill=_ink(colour, 0.95))
    draw.polygon([(s * 0.30, s * 0.62), (s * 0.70, s * 0.62), (s * 0.78, s * 0.76), (s * 0.22, s * 0.76)],
                 fill=_ink(colour, 1.25))
    for cx, cy, r in ((s * 0.30, s * 0.40, 0.035), (s * 0.72, s * 0.34, 0.025)):
        draw.ellipse([s * cx - s * r, s * cy - s * r, s * cx + s * r, s * cy + s * r], fill=_ink(colour, 1.15))
    draw.rounded_rectangle([s * 0.40, s * 0.18, s * 0.60, s * 0.26], radius=int(s * 0.02), fill=_ink(colour, 0.8))


def draw_tools_instruments(draw: ImageDraw.ImageDraw, colour):
    """A gear beside a spanner-like bar."""
    s = SIZE * SUPERSAMPLE
    cx, cy, r = s * 0.56, s * 0.52, s * 0.20
    import math

    teeth = 10
    for index in range(teeth):
        angle = 2 * math.pi * index / teeth
        x = cx + math.cos(angle) * r * 1.32
        y = cy + math.sin(angle) * r * 1.32
        draw.rounded_rectangle([x - s * 0.045, y - s * 0.045, x + s * 0.045, y + s * 0.045],
                               radius=int(s * 0.012), fill=_ink(colour, 0.85))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_ink(colour, 1.05))
    draw.ellipse([cx - r * 0.34, cy - r * 0.34, cx + r * 0.34, cy + r * 0.34], fill=(255, 255, 255))


DRAWERS = {
    "general": draw_general,
    "everyday": draw_everyday,
    "people_society": draw_people_society,
    "geography_environment": draw_geography_environment,
    "language": draw_language,
    "transport": draw_transport,
    "nature": draw_nature,
    "business": draw_business,
    "technology": draw_technology,
    "science_medicine": draw_science_medicine,
    "tools_instruments": draw_tools_instruments,
}


def render(category: str, out_dir: Path) -> Path:
    colour = CATEGORIES[category][1]
    image, draw = _canvas(colour)
    DRAWERS[category](draw, colour)
    # A hairline frame keeps the illustration readable on any background shade.
    draw.rectangle([0, 0, image.width - 1, image.height - 1], outline=_ink(colour, 0.5), width=SUPERSAMPLE * 3)
    image = image.resize((SIZE, SIZE), Image.LANCZOS)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{category}.webp"
    image.save(path, "WEBP", quality=88, method=6)
    return path


def register(db_path: Path, asset_dir: Path) -> None:
    """Insert one image row per category, then map every uncovered entry to it."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    inserted: dict[str, int] = {}

    for category in CATEGORIES:
        asset = asset_dir / f"{category}.webp"
        if not asset.exists():
            raise SystemExit(f"missing asset {asset}; run without --register first")
        # Flutter asset keys are POSIX-style; a Windows backslash never resolves.
        asset_key = asset.as_posix()
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        existing = con.execute("SELECT image_id FROM images WHERE sha256 = ?", (digest,)).fetchone()
        if existing:
            inserted[category] = existing["image_id"]
            continue
        cursor = con.execute(
            """
            INSERT INTO images (content_hash, title, thumb_path, detail_path, width, height,
                                source, source_url, author, license, license_url, attribution_text,
                                status, asset_status, license_status, sha256, thumb_asset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', 'approved', 'verified', ?, ?)
            """,
            (
                digest, f"Category illustration: {CATEGORIES[category][0]}",
                asset_key, asset_key, SIZE, SIZE,
                "project_illustration", "", "Trilingual Dictionary project",
                "CC0-1.0 (project-generated)", "https://creativecommons.org/publicdomain/zero/1.0/",
                f"Category illustration drawn in code — {CATEGORIES[category][0]} — CC0",
                digest, asset_key,
            ),
        )
        inserted[category] = cursor.lastrowid
        con.commit()

    # Only entries with no image at all are touched: a real photograph always wins.
    filled = 0
    for entry_id, category in con.execute(
        """
        SELECT e.entry_id, e.category FROM entries e
        WHERE NOT EXISTS (SELECT 1 FROM entry_images ei WHERE ei.entry_id = e.entry_id)
        """
    ).fetchall():
        image_id = inserted.get(category) or inserted["general"]
        # Rank 2, so a real photograph added later (rank 1) always outranks the
        # illustration without needing to delete or rewrite these rows.
        con.execute(
            """
            INSERT INTO entry_images (entry_id, sense_id, image_id, confidence, rank,
                                      match_method, match_reason)
            VALUES (?, NULL, ?, 0.2, 2, 'category-fallback', ?)
            """,
            (entry_id, image_id, f"no photograph available; category illustration ({category})"),
        )
        filled += 1
    con.commit()

    remaining = con.execute(
        """
        SELECT COUNT(*) FROM entries e
        WHERE NOT EXISTS (SELECT 1 FROM entry_images ei WHERE ei.entry_id = e.entry_id)
        """
    ).fetchone()[0]
    with_photo = con.execute(
        "SELECT COUNT(*) FROM entry_images WHERE match_method <> 'category-fallback'"
    ).fetchone()[0]
    print(f"illustrations registered: {len(inserted)}")
    print(f"entries mapped to a category illustration: {filled}")
    print(f"entries still without any image: {remaining}")
    print(f"entries with a real photograph: {with_photo}")
    con.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("assets/images/categories"))
    parser.add_argument("--db", type=Path, default=Path("data/build/dictionary.sqlite"))
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args(argv[1:])

    for category in CATEGORIES:
        path = render(category, args.out)
        print(f"drew {category:<24} -> {path}")
    if args.register:
        register(args.db, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
