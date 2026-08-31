#!/usr/bin/env python3
"""Generate the three-direction artboard set for the paid-beta design decision.

All odds, consensus numbers, book names, spreads and events are REAL, read
from tonight's stores (2026-08-31). Matchup factor stats are representative
mockup content (marked at handover); no probabilities, no predictions, no EV.
"""
import json, os

OUT = os.path.dirname(os.path.abspath(__file__))

# ---- shared real data (from data/processed/odds_multibook.jsonl, 22:16Z) ----
SD_CIN_BOARD = [  # book, away, home  (Padres @ Reds, first pitch 22:41Z / 6:41 ET)
    ("FanDuel", -134, 114), ("DraftKings", -142, 118), ("BetMGM", -140, 115),
    ("Caesars", -130, 120), ("BetRivers", -159, 133), ("Bovada", -135, 113),
    ("BetOnline", -130, 118), ("Lowvig", -130, 118), ("Fanatics", -150, 125),
    ("BetUS", -144, 130), ("MyBookie", -152, 129),
]

DIRS = {
 "A": dict(
   key="A", name="Editorial", tag="Editorial · Spacious",
   motive="Reads like a broadsheet: the evidence is prose first, numbers second. Calmest of the three; strongest fit for the honesty positioning.",
   tradeoff="Least dense — power users will want more on screen at once.",
   font_head="'Source Serif 4', Georgia, serif", font_body="'Source Sans 3', 'Segoe UI', sans-serif",
   font_mono="'IBM Plex Mono', 'SFMono-Regular', monospace",
   gf="family=Source+Serif+4:wght@500;600&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@400;500",
   bg="#1B1917", panel="#22201D", panel2="#282520", line="#37332D", text="#EAE6DF",
   mut="#A39B8F", faint="#736B60", cyan="#8AD4E2", amber="#D9A441", red="#C0604F",
   radius="4px", pad="28px", gap="22px", h1="30px", h2="19px", body="15.5px", small="13px",
   headweight="600", lh="1.55", border="1px solid #37332D",
 ),
 "B": dict(
   key="B", name="Terminal", tag="Terminal · Precision",
   motive="Professional market-intelligence register at consumer access — the white space the naming research found. Dense where density earns it; every number tabular.",
   tradeoff="Coldest of the three; new bettors may need the Quick View to carry more warmth.",
   font_head="'IBM Plex Sans', 'Segoe UI', sans-serif", font_body="'IBM Plex Sans', 'Segoe UI', sans-serif",
   font_mono="'IBM Plex Mono', 'SFMono-Regular', monospace",
   gf="family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500",
   bg="#191817", panel="#201E1C", panel2="#262421", line="#3A362F", text="#E7E3DC",
   mut="#9C948A", faint="#6E675D", cyan="#7FCFDE", amber="#D7A23B", red="#BD5D4C",
   radius="2px", pad="20px", gap="14px", h1="24px", h2="16px", body="14px", small="12.5px",
   headweight="600", lh="1.45", border="1px solid #3A362F",
 ),
 "C": dict(
   key="C", name="Clubhouse", tag="Sports · Warm",
   motive="Sports-native warmth on the same graphite: bigger team identity, softer surfaces. Most inviting for the casual-serious persona.",
   tradeoff="Closest to what sports media already looks like — least differentiated register.",
   font_head="'Archivo', 'Segoe UI', sans-serif", font_body="'Source Sans 3', 'Segoe UI', sans-serif",
   font_mono="'JetBrains Mono', 'SFMono-Regular', monospace",
   gf="family=Archivo:wght@600;700&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;500",
   bg="#201C19", panel="#2A2521", panel2="#312B26", line="#443C34", text="#EFE9E1",
   mut="#B0A698", faint="#7C7264", cyan="#8AD4E2", amber="#E0A94C", red="#C0604F",
   radius="10px", pad="24px", gap="18px", h1="28px", h2="18px", body="15px", small="13px",
   headweight="700", lh="1.5", border="1px solid #443C34",
 ),
}

def shell(d, title, inner, width=1240):
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?{d['gf']}&display=swap">
  <style>
    body {{ margin: 0; background: {d['bg']}; color: {d['text']};
           font-family: {d['font_body']}; font-size: {d['body']}; line-height: {d['lh']}; }}
    a {{ color: {d['cyan']}; text-decoration: none; }} a:hover {{ color: {d['amber']}; }}
  </style>
</helmet>
{inner}
</x-dc>
</body>
</html>"""

def chip(d, txt, color=None, borderless=False):
    c = color or d["mut"]
    return (f'<span style="font-family: {d["font_mono"]}; font-size: 11px; color: {c}; '
            f'border: 1px solid {c}55; border-radius: {d["radius"]}; padding: 2px 8px; white-space: nowrap;">{txt}</span>')

def nav(d, active="Today", w="1240px"):
    items = "".join(
        f'<div style="padding: 10px 16px; font-weight: {"600" if it==active else "400"}; '
        f'color: {d["text"] if it==active else d["mut"]}; '
        f'border-bottom: 2px solid {d["amber"] if it==active else "transparent"};">{it}</div>'
        for it in ["Today","Games","Bet Check","Odds","My Bets"])
    return (f'<div style="display: flex; align-items: center; gap: 4px; border-bottom: {d["border"]}; '
            f'padding: 0 {d["pad"]}; background: {d["bg"]};">'
            f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: 17px; '
            f'padding-right: 20px; letter-spacing: 0.3px;">WORKING&nbsp;TITLE</div>'
            f'{items}'
            f'<div style="margin-left: auto; display: flex; gap: 14px; align-items: center;">'
            f'{chip(d, "Odds updated 2 min ago", d["cyan"])}'
            f'<div style="width: 30px; height: 30px; border-radius: 50%; background: {d["panel2"]}; '
            f'border: {d["border"]};"></div></div></div>')

def board_rows(d, board, best_away=-130):
    rows = ""
    for book, away, home in board:
        hl = away == best_away
        rows += (f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; '
                 f'padding: 7px 12px; border-bottom: 1px solid {d["line"]}66; align-items: center; '
                 f'background: {d["amber"]+"14" if hl else "transparent"};">'
                 f'<div style="color: {d["mut"]}; font-size: {d["small"]};">{book}</div>'
                 f'<div style="font-family: {d["font_mono"]}; text-align: right; '
                 f'color: {d["amber"] if hl else d["text"]};">{away:+d}</div>'
                 f'<div style="font-family: {d["font_mono"]}; text-align: right; color: {d["text"]};">{home:+d}</div>'
                 f'</div>')
    return rows

def factor(d, side_label, side_color, title, body, sample, label=None):
    lab = f' {chip(d, label, d["cyan"])}' if label else ""
    return (f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
            f'padding: {d["pad"]}; display: flex; flex-direction: column; gap: 8px;">'
            f'<div style="display: flex; gap: 10px; align-items: baseline;">'
            f'<span style="font-family: {d["font_mono"]}; font-size: 11px; color: {side_color}; '
            f'letter-spacing: 1px;">{side_label}</span>{lab}</div>'
            f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h2"]};">{title}</div>'
            f'<div style="color: {d["mut"]};">{body}</div>'
            f'<div style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["faint"]};">{sample}</div>'
            f'</div>')

# ---------------------------------------------------------------- TODAY -----
def today(d):
    changed = (
      f'<div style="background: {d["panel2"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: 14px {d["pad"]}; display: flex; gap: 26px; align-items: center;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; '
      f'color: {d["amber"]};">WHAT CHANGED</span>'
      f'<div style="display: flex; gap: 22px; flex-wrap: wrap; color: {d["mut"]}; font-size: {d["small"]};">'
      f'<span><span style="color: {d["text"]};">Lineups posted for 10 of 12 games</span> · latest 5:16 ET</span>'
      f'<span><span style="color: {d["text"]};">Books split on Tigers–Twins</span> · 4 of 11 books price Detroit as the underdog</span>'
      f'<span>Blue Jays optioned RHP C.J. Van Eyk · no game tonight affected</span>'
      f'</div></div>')
    verdict = (
      f'<div style="padding: {d["pad"]}; display: flex; flex-direction: column; gap: 6px;">'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h1"]};">'
      f'We checked all 12 games. Nothing clears the bar tonight.</div>'
      f'<div style="color: {d["mut"]}; max-width: 720px;">Every matchup was run through the full battery — '
      f'lineups, starters, bullpens, prices across 11 books. A quiet night is a finding, not a blank page. '
      f'The closest calls and the market context are below.</div></div>')
    cards = ""
    games = [
      ("Padres @ Reds", "6:41 ET", "SD 56.3% · CIN 43.7%",
       "Closest call tonight: Reds' right-heavy order faces a left-handed starter, but the sample behind the split is thin.",
       "consensus of 11 books", d["cyan"]),
      ("Tigers @ Twins", "7:41 ET", "DET 50.1% · MIN 49.9%",
       "The books disagree about the favorite — 7 price Detroit ahead, 4 price Minnesota. A genuine coin-flip board.",
       "widest book split on the slate", d["amber"]),
      ("Yankees @ Angels", "9:38 ET", "NYY 58.7% · LAA 41.3%",
       "69-cent spread on the away price (−117 to −186). Where you bet matters more than what you bet tonight.",
       "largest price spread", d["amber"]),
    ]
    for name, t, cons, note, tag, tagc in games:
        cards += (
          f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
          f'padding: {d["pad"]}; display: flex; flex-direction: column; gap: 10px;">'
          f'<div style="display: flex; justify-content: space-between; align-items: baseline;">'
          f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h2"]};">{name}</div>'
          f'<span style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["faint"]};">{t}</span></div>'
          f'<div style="font-family: {d["font_mono"]}; font-size: 13px; color: {d["mut"]};">{cons} '
          f'<span style="color: {d["faint"]};">market-implied consensus</span></div>'
          f'<div style="color: {d["mut"]};">{note}</div>'
          f'<div>{chip(d, tag, tagc)}</div></div>')
    price_note = (
      f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: {d["pad"]}; color: {d["mut"]}; font-size: {d["small"]};">'
      f'<span style="color: {d["amber"]}; font-family: {d["font_mono"]}; font-size: 11px; '
      f'letter-spacing: 1.5px;">PRICES TONIGHT</span><br>'
      f'No board beats the market-implied consensus right now — normal, because a quoted price still carries '
      f'the book&rsquo;s margin and the consensus has had it removed. The best numbers on each side are in '
      f'<a href="#">Odds</a>.</div>')
    inner = (nav(d) + f'<div style="display: flex; flex-direction: column; gap: {d["gap"]}; padding: {d["gap"]} {d["pad"]} 40px;">'
             + changed + verdict
             + f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: {d["gap"]};">{cards}</div>'
             + price_note + '</div>')
    return shell(d, "Today", inner)

# ----------------------------------------------------------------- GAME -----
def game(d):
    head = (
      f'<div style="padding: {d["pad"]}; display: flex; justify-content: space-between; align-items: flex-end; '
      f'border-bottom: {d["border"]};">'
      f'<div><div style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["faint"]};">Sunday, August 31 · 6:41 ET · Great American Ball Park</div>'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h1"]};">San Diego Padres @ Cincinnati Reds</div></div>'
      f'<div style="text-align: right;"><div style="font-family: {d["font_mono"]}; font-size: 13px; color: {d["mut"]};">SD 56.3% · CIN 43.7%</div>'
      f'<div style="font-size: 11px; color: {d["faint"]};">market-implied consensus · 11 books</div></div></div>')
    factors = "".join((
      factor(d, "LEANS PADRES", d["cyan"], "Cincinnati&rsquo;s right-handed core loses its platoon edge tonight",
             "The Reds&rsquo; three best bats hit right-handed and face a right-handed starter — the favorable split they had the last two nights is gone.",
             "sample: 402 plate appearances vs RHP this season", "Observation"),
      factor(d, "LEANS REDS", d["red"], "San Diego&rsquo;s bullpen worked both ends of a doubleheader Friday",
             "Five Padres relievers threw yesterday; the two highest-leverage arms threw 25+ pitches. A close game reaches a thinner pen than the season numbers suggest.",
             "sample: 9 relievers, 214 pitches over the last 3 days", "Observation"),
      factor(d, "PRICE", d["amber"], "Best Padres price is −130; the widest book is 29 cents worse",
             "Three books post −130 (BetOnline, Caesars, Lowvig); BetRivers posts −159. Same bet, meaningfully different number — this is line-shopping value, not a prediction.",
             "board of 11 books · updated 6:16 ET"),
      factor(d, "CONTEXT", d["mut"], "Interesting matchup, but no demonstrated betting edge",
             "Nothing tonight clears the evidence bar this product holds itself to. The factors above are context for your own judgment, not a recommendation.",
             "27 pre-registered research hypotheses tested to date · zero survived"),
    ))
    adv = (
      f'<div style="border-top: {d["border"]}; padding: {d["pad"]}; display: flex; flex-direction: column; gap: 10px;">'
      f'<div style="display: flex; align-items: center; gap: 12px;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; color: {d["faint"]};">ADVANCED</span>'
      f'<span style="color: {d["faint"]}; font-size: {d["small"]};">full splits, pitch mix, bullpen ledger, market table — expands below, never replaces the summary</span>'
      f'<span style="margin-left: auto; color: {d["cyan"]};">Expand ▾</span></div></div>')
    inner = (nav(d, "Games") + head
             + f'<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: {d["gap"]}; padding: {d["gap"]} {d["pad"]};">{factors}</div>'
             + adv)
    return shell(d, "Game", inner)

# ------------------------------------------------------------- BET CHECK ----
def betcheck(d, mobile=False):
    pad = "16px" if mobile else d["pad"]
    grid_cols = "1fr" if mobile else "repeat(2, minmax(0, 1fr))"
    your_bet = (
      f'<div style="background: {d["panel2"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: {pad}; display: flex; flex-direction: column; gap: 6px;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; color: {d["faint"]};">YOUR BET</span>'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h1"]};">Padres ML <span style="font-family: {d["font_mono"]};">−134</span></div>'
      f'<div style="color: {d["mut"]}; font-size: {d["small"]};">@ Reds · tonight 6:41 ET · price as entered</div></div>')
    support = factor(d, "SUPPORTS YOUR BET", d["cyan"],
      "The platoon math tilts your way",
      "Cincinnati&rsquo;s best hitters lose their left-right advantage against tonight&rsquo;s starter, and the consensus already makes your side a 56% favorite.",
      "sample: 402 PA vs RHP · consensus of 11 books")
    against = factor(d, "AGAINST YOUR BET", d["red"],
      "You are paying more than the best board price",
      "Three books post −130 for the same bet. At your −134, you give up 4 cents of price on identical risk — and San Diego&rsquo;s bullpen is short after Friday&rsquo;s doubleheader.",
      "board of 11 books · 9 relievers, 214 pitches / 3 days")
    market = (
      f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; padding: {pad};">'
      f'<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; color: {d["amber"]};">PRICE</span>'
      f'<span style="font-size: 11px; color: {d["faint"]};">updated 6:16 ET</span></div>'
      f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; text-align: center;">'
      f'<div><div style="font-family: {d["font_mono"]}; font-size: 22px; color: {d["amber"]};">−130</div>'
      f'<div style="font-size: 11px; color: {d["faint"]};">best available<br>BetOnline · Caesars · Lowvig</div></div>'
      f'<div><div style="font-family: {d["font_mono"]}; font-size: 22px; color: {d["text"]};">−129</div>'
      f'<div style="font-size: 11px; color: {d["faint"]};">market-implied consensus<br>as a price</div></div>'
      f'<div><div style="font-family: {d["font_mono"]}; font-size: 22px; color: {d["mut"]};">−134</div>'
      f'<div style="font-size: 11px; color: {d["faint"]};">your price<br>4 cents shy of best</div></div>'
      f'</div></div>')
    bottom = (
      f'<div style="background: {d["panel2"]}; border-left: 3px solid {d["amber"]}; border-radius: {d["radius"]}; '
      f'padding: {pad}; display: flex; flex-direction: column; gap: 6px;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; color: {d["faint"]};">BOTTOM LINE</span>'
      f'<div style="font-size: {d["body"]};">The market broadly agrees with your side — and disagrees with your price. '
      f'If you make this bet, three books offer the same position at −130. '
      f'<span style="color: {d["mut"]};">No demonstrated predictive edge exists on this game; that is a price observation, not a prediction.</span></div></div>')
    stack = f'<div style="display: flex; flex-direction: column; gap: {d["gap"]}; padding: {d["gap"]} {pad} 40px;">'
    if mobile:
        inner = (f'<div style="display: flex; flex-direction: column; min-height: 844px; background: {d["bg"]};">'
                 f'<div style="padding: 14px 16px; border-bottom: {d["border"]}; font-family: {d["font_head"]}; '
                 f'font-weight: {d["headweight"]};">Bet Check</div>'
                 + stack + your_bet + support + against + market + bottom + '</div>'
                 f'<div style="margin-top: auto; display: flex; border-top: {d["border"]};">'
                 + "".join(f'<div style="flex: 1 1 0; text-align: center; padding: 12px 0; font-size: 11px; '
                           f'color: {d["amber"] if it=="Bet Check" else d["faint"]};">{it}</div>'
                           for it in ["Today","Games","Bet Check","Odds","My Bets"])
                 + '</div></div>')
    else:
        inner = (nav(d, "Bet Check") + stack + your_bet
                 + f'<div style="display: grid; grid-template-columns: {grid_cols}; gap: {d["gap"]};">{support}{against}</div>'
                 + market + bottom + '</div>')
    return shell(d, "Bet Check", inner)

# ------------------------------------------------------------------ MAIN ----
def main_cover():
    d = DIRS["B"]
    rows = ""
    for k in "ABC":
        dd = DIRS[k]
        rows += (f'<div style="background: {dd["panel"]}; border: 1px solid {dd["line"]}; border-radius: {dd["radius"]}; '
                 f'padding: 22px; display: flex; flex-direction: column; gap: 8px;">'
                 f'<div style="font-family: {dd["font_head"]}; font-weight: {dd["headweight"]}; font-size: 20px;">'
                 f'Direction {k} — {dd["name"]} <span style="color: {dd["faint"]}; font-weight: 400;">({dd["tag"]})</span></div>'
                 f'<div style="color: {dd["mut"]};">{dd["motive"]}</div>'
                 f'<div style="color: {dd["faint"]}; font-size: 13px;">Tradeoff: {dd["tradeoff"]}</div></div>')
    inner = (f'<div style="max-width: 860px; margin: 0 auto; padding: 48px 40px; display: flex; '
             f'flex-direction: column; gap: 18px;">'
             f'<div style="font-family: {d["font_mono"]}; font-size: 12px; letter-spacing: 2px; color: {d["amber"]};">VISUAL DIRECTION DECISION</div>'
             f'<div style="font-family: {d["font_head"]}; font-weight: 600; font-size: 30px;">Three executions of the same product. Pick one.</div>'
             f'<div style="color: {d["mut"]};">Same information architecture, same evidence rules, same real slate '
             f'(Sunday, August 31 — odds as captured at 6:16 ET from 11 books). Each direction shows Today, one game, '
             f'and Bet Check, plus Bet Check at phone width. Recommendation: <b style="color: {d["text"]};">Direction B (Terminal)</b> — '
             f'it owns the register no consumer competitor uses; A is the strongest alternative if it reads too cold.</div>'
             + rows + '</div>')
    return shell(d, "Main", inner)

# ------------------------------------------------------------------ emit ----
files = {"Main.dc.html": main_cover()}
for k, dd in DIRS.items():
    files[f"{k}Today.dc.html"] = today(dd)
    files[f"{k}Game.dc.html"] = game(dd)
    files[f"{k}BetCheck.dc.html"] = betcheck(dd)
    files[f"{k}Mobile.dc.html"] = betcheck(dd, mobile=True)

for name, src in files.items():
    open(os.path.join(OUT, name), "w").write(src)

# canvas layout: cover top-left; one row per direction; mobiles at row end
boards = [{"file": "Main.dc.html", "x": 0, "y": 0, "w": 900, "h": 640}]
y = 800
for k in "ABC":
    x = 0
    for screen, w, h in [("Today", 1240, 900), ("Game", 1240, 860), ("BetCheck", 1240, 980), ("Mobile", 390, 844)]:
        boards.append({"file": f"{k}{screen}.dc.html", "x": x, "y": y, "w": w, "h": h,
                       "title": f"{DIRS[k]['name']} — {screen if screen!='Mobile' else 'Bet Check 375px'}"})
        x += w + 100
    y += 1120
canvas = {"artboards": boards,
          "annotations": [{"id": "decision-note", "x": 960, "y": 40, "w": 300,
                           "text": "Rows top to bottom: A Editorial, B Terminal, C Clubhouse (Sports-Warm).\nOdds and book names are real (captured 6:16 ET tonight).\nMatchup factor stats are representative sample content."}],
          "launch": {"view": "canvas"}}
open(os.path.join(OUT, "canvas.json"), "w").write(json.dumps(canvas, indent=1))
print("wrote", len(files), "artboards + canvas.json")
