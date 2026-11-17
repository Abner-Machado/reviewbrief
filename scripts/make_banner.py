#!/usr/bin/env python3
"""Draw the repository banner.

The image is the point of the tool, so it shows the tool's own output: a line
number column that is actually correct, and a signal pointing at a line you
could go and open.

    python scripts/make_banner.py assets/banner.png

Needs Pillow. Nothing else in this repository does, which is why this lives in
scripts/ and not next to reviewbrief.py.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 640

BG = (12, 12, 14)
PANEL = (22, 22, 26)
EDGE = (42, 42, 48)
FG = (236, 236, 238)
DIM = (128, 130, 138)
NUM = (224, 153, 92)      # the line number column, the whole argument
WARN = (224, 153, 92)
GREEN = (126, 186, 140)

CODE = [
    ("11", '    print("debug", name)', "debug-leftover"),
    ("12", '    query = "SELECT * FROM users WHERE name = \'" + name + "\'"', None),
    ("13", '    api_key = "sk-abcdef0123456789"', "secret-like"),
    ("14", "    return db.run(query)", None),
]

WIN_FONTS = r"C:\Windows\Fonts"
CANDIDATES = {
    "mono": ["consola.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
    "mono_bold": ["consolab.ttf", "DejaVuSansMono-Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"],
    "sans": ["segoeui.ttf", "DejaVuSans.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "sans_bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}


def load(kind, size):
    for name in CANDIDATES[kind]:
        for path in (name, os.path.join(WIN_FONTS, name)):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main(out="assets/banner.png"):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    f_title = load("sans_bold", 62)
    f_tag = load("sans", 27)
    f_small = load("mono", 19)
    f_code = load("mono", 20)
    f_num = load("mono_bold", 20)
    f_foot = load("mono", 18)

    # a hairline rule across the top, the only decoration
    d.rectangle([0, 0, W, 3], fill=NUM)

    x = 74
    d.text((x, 92), "reviewbrief", font=f_title, fill=FG)
    d.text((x, 172), "line numbers that exist", font=f_tag, fill=NUM)
    d.text((x, 214), "A code review brief built from the diff,", font=f_tag, fill=DIM)
    d.text((x, 248), "so every citation points somewhere real.", font=f_tag, fill=DIM)

    # the panel: the tool's own output
    px, py, pw, ph = 74, 330, W - 148, 206
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=10, fill=PANEL, outline=EDGE)

    d.text((px + 24, py + 20), "$ git diff | python reviewbrief.py",
           font=f_small, fill=GREEN)

    top = py + 58
    step = 30
    for i, (num, text, signal) in enumerate(CODE):
        y = top + i * step
        d.text((px + 24, y), num.rjust(6), font=f_num, fill=NUM)
        d.text((px + 118, y), text, font=f_code, fill=FG)
        if signal:
            w = d.textlength(text, font=f_code)
            d.text((px + 134 + w, y), "<- " + signal, font=f_code, fill=WARN)

    d.text((74, H - 56), "MIT  ·  python standard library only  ·  no network",
           font=f_foot, fill=DIM)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    img.save(out)
    print("wrote %s  %dx%d" % (out, W, H))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "assets/banner.png"))
