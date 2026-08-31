#!/usr/bin/env python3
"""Build the human review deck: render artboards headlessly -> PNGs -> 26-page PDF."""
import os, re, sys
from playwright.sync_api import sync_playwright
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
STAND = os.path.join(HERE, "standalone"); os.makedirs(STAND, exist_ok=True)
SHOTS = os.path.join(HERE, "shots"); os.makedirs(SHOTS, exist_ok=True)
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

def standalone(name):
    """Strip support.js / x-dc / helmet into plain HTML."""
    src = open(os.path.join(HERE, name)).read()
    src = src.replace('<script src="./support.js"></script>', '')
    src = src.replace('<x-dc>', '').replace('</x-dc>', '')
    m = re.search(r'<helmet>(.*?)</helmet>', src, re.S)
    head = m.group(1) if m else ''
    src = re.sub(r'<helmet>.*?</helmet>', '', src, flags=re.S)
    src = src.replace('</head>', head + '</head>')
    out = os.path.join(STAND, name.replace('.dc.html', '.html'))
    open(out, 'w').write(src)
    return out

# (artboard file, shot name, viewport width, device scale)
JOBS = []
for k in "ABC":
    JOBS += [
        (f"{k}Today.dc.html",        f"{k}_today.png",           1240, 2),
        (f"{k}Game.dc.html",         f"{k}_game.png",            1240, 2),
        (f"{k}GameAdvanced.dc.html", f"{k}_game_advanced.png",   1240, 2),
        (f"{k}BetCheck.dc.html",     f"{k}_betcheck.png",        1240, 2),
        (f"{k}TodayPhone.dc.html",   f"{k}_mobile_today.png",     390, 3),
        (f"{k}GamePhone.dc.html",    f"{k}_mobile_game.png",      390, 3),
        (f"{k}BetCheckPhone.dc.html",f"{k}_mobile_betcheck.png",  390, 3),
    ]

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=CHROME)
    for board, shot, w, dsf in JOBS:
        page = browser.new_page(viewport={"width": w, "height": 900}, device_scale_factor=dsf)
        page.goto("file://" + standalone(board))
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(SHOTS, shot), full_page=True)
        page.close()
        print("shot", shot)
    browser.close()

# ---------------- PDF assembly ----------------
# Letter-ish canvas at 150dpi: 1275 x 1650 portrait. Desktop shots nearly fill
# the width; mobile shots are enlarged to ~62% of page height readable.
PW, PH, MARGIN, DARK = 1275, 1650, 42, (18, 17, 16)
LIGHT = (234, 230, 223); MUT = (150, 143, 133)

try:
    from PIL import ImageFont
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    FONT_S = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
except Exception:
    from PIL import ImageFont
    FONT = FONT_S = ImageFont.load_default()

from PIL import ImageDraw

def page_with(title, subtitle, images, mobile=False):
    """One PDF page: header + image(s). images = list of (path, target_w)."""
    n = len(images)
    stack = n > 1 and all(Image.open(p).width > Image.open(p).height * 0.8 for p, _ in images)
    ph = PH
    if stack:  # wide images: stacked full-width on one tall page
        gap = 30
        tw = PW - 2 * MARGIN
        hs = [int(Image.open(p).height * tw / Image.open(p).width) for p, _ in images]
        ph = MARGIN + 92 + sum(hs) + gap * (n - 1) + MARGIN
    pg = Image.new("RGB", (PW, ph), DARK)
    dr = ImageDraw.Draw(pg)
    dr.text((MARGIN, MARGIN), title, fill=LIGHT, font=FONT)
    for li, line in enumerate(subtitle.split("\n")):
        dr.text((MARGIN, MARGIN + 42 + 26 * li), line, fill=MUT, font=FONT_S)
    top = MARGIN + 92
    if stack:
        labels = ["A — Editorial", "B — Terminal", "C — Clubhouse"]
        y = top
        for i, (path, _) in enumerate(images):
            dr.text((MARGIN, y - 4), "", fill=MUT, font=FONT_S)
            im = Image.open(path)
            tw = PW - 2 * MARGIN
            th = int(im.height * tw / im.width)
            pg.paste(im.resize((tw, th), Image.LANCZOS), (MARGIN, y))
            y += th + 30
        return pg
    if n == 1:
        path, _ = images[0]
        im = Image.open(path)
        tw = PW - 2 * MARGIN if not mobile else 560
        th = int(im.height * tw / im.width)
        avail = PH - top - MARGIN
        if th > avail:  # split tall shots across... no: scale to fit but keep readable min
            th = avail; tw = int(im.width * th / im.height)
        im = im.resize((tw, th), Image.LANCZOS)
        pg.paste(im, ((PW - tw) // 2, top))
    else:  # comparison: n images side by side
        gap = 24
        tw = (PW - 2 * MARGIN - gap * (n - 1)) // n
        x = MARGIN
        maxh = PH - top - MARGIN
        for path, _ in images:
            im = Image.open(path)
            th = int(im.height * tw / im.width)
            if th > maxh:
                th = maxh; w2 = int(im.width * th / im.height)
            else:
                w2 = tw
            im = im.resize((w2, th), Image.LANCZOS)
            pg.paste(im, (x + (tw - w2) // 2, top))
            x += tw + gap
    return pg

NAMES = {"A": "Direction A — Editorial / Spacious",
         "B": "Direction B — Terminal / Precision",
         "C": "Direction C — Clubhouse / Sports-Warm"}
CAP = "Real slate + odds (Sun Aug 31, 11 books, 6:16 ET) · factor stats are sample content · no predictions"

pages = []

# Page 1 — overview
pg = Image.new("RGB", (PW, PH), DARK); dr = ImageDraw.Draw(pg)
y = 140
dr.text((MARGIN, y), "Betting Intelligence — Visual Directions", fill=LIGHT, font=FONT); y += 70
dr.text((MARGIN, y), "Three executions of the same product. Pick one.", fill=MUT, font=FONT_S); y += 70
for k, blurb in [("A", "Editorial / Spacious — broadsheet calm; prose first, numbers second."),
                 ("B", "Terminal / Precision — market-intelligence register; dense where density earns it.  << recommended"),
                 ("C", "Clubhouse / Sports-Warm — sports-native warmth; most inviting, least differentiated.")]:
    dr.text((MARGIN, y), NAMES[k], fill=LIGHT, font=FONT); y += 44
    dr.text((MARGIN, y), blurb, fill=MUT, font=FONT_S); y += 76
y += 30
for line in ["Pages 2-8: Direction A   ·   Pages 9-15: Direction B   ·   Pages 16-22: Direction C",
             "Each direction: Today, Game quick, Game advanced, Bet Check (desktop), then Today / Game / Bet Check (mobile).",
             "Pages 23-26: side-by-side comparisons — Bet Check desktop, Bet Check mobile, Today desktop, Today mobile.",
             "", CAP]:
    dr.text((MARGIN, y), line, fill=MUT, font=FONT_S); y += 34
pages.append(pg)

ORDER = [("today", "TODAY — desktop", False), ("game", "GAME quick view — desktop", False),
         ("game_advanced", "GAME with Advanced expanded — desktop", False),
         ("betcheck", "BET CHECK — desktop", False),
         ("mobile_today", "TODAY — mobile 375px", True),
         ("mobile_game", "GAME — mobile 375px", True),
         ("mobile_betcheck", "BET CHECK — mobile 375px", True)]

for k in "ABC":
    for stem, label, mob in ORDER:
        pages.append(page_with(NAMES[k], label + "\n" + CAP,
                               [(os.path.join(SHOTS, f"{k}_{stem}.png"), 0)], mobile=mob))

for stem, label in [("betcheck", "BET CHECK desktop — A / B / C"),
                    ("mobile_betcheck", "BET CHECK mobile — A / B / C"),
                    ("today", "TODAY desktop — A / B / C"),
                    ("mobile_today", "TODAY mobile — A / B / C")]:
    pages.append(page_with("Comparison", label,
                           [(os.path.join(SHOTS, f"{k}_{stem}.png"), 0) for k in "ABC"]))

out_pdf = os.path.join(HERE, "betting-intelligence-visual-directions-review.pdf")
pages[0].save(out_pdf, save_all=True, append_images=pages[1:], resolution=150)
print("PDF:", out_pdf, len(pages), "pages", os.path.getsize(out_pdf) // 1024, "KB")
