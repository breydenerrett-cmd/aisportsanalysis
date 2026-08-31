#!/usr/bin/env python3
"""Generate the three-direction review package for the paid-beta design decision.

Structure (per Brey's visual-review delivery correction, 2026-08-31):
- START HERE page: cover with how-to-review + recommendation.
- One page per direction (A/B/C), each a VERTICAL stack of SEVEN views:
  Bet Check desktop, Bet Check 375px, Today desktop, Today 375px,
  Game quick desktop, Game advanced (expanded) desktop, Game 375px.
- One BET CHECK COMPARISON page: all three directions full-size, desktop
  row + mobile row, with the meaningful differences stated.

All odds, consensus numbers, book names, spreads and events are REAL, read
from tonight's stores (2026-08-31). Matchup factor stats are representative
mockup content (marked at handover); no probabilities, no predictions, no EV.
"""
import json, os

OUT = os.path.dirname(os.path.abspath(__file__))

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
   key="C", name="Clubhouse", tag="Clubhouse · Sports-Warm",
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

def shell(d, title, inner):
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

def chip(d, txt, color=None):
    c = color or d["mut"]
    return (f'<span style="font-family: {d["font_mono"]}; font-size: 11px; color: {c}; '
            f'border: 1px solid {c}55; border-radius: {d["radius"]}; padding: 2px 8px; white-space: nowrap;">{txt}</span>')

def nav(d, active="Today"):
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

def tabbar(d, active):
    return (f'<div style="margin-top: auto; display: flex; border-top: {d["border"]}; background: {d["bg"]};">'
            + "".join(f'<div style="flex: 1 1 0; text-align: center; padding: 12px 0; font-size: 11px; '
                      f'color: {d["amber"] if it==active else d["faint"]};">{it}</div>'
                      for it in ["Today","Games","Bet Check","Odds","My Bets"])
            + '</div>')

def mobile_head(d, title):
    return (f'<div style="padding: 14px 16px; border-bottom: {d["border"]}; display: flex; '
            f'justify-content: space-between; align-items: baseline;">'
            f'<span style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: 18px;">{title}</span>'
            f'<span style="font-family: {d["font_mono"]}; font-size: 10px; color: {d["cyan"]};">odds 2 min ago</span></div>')

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

def factor(d, side_label, side_color, title, body, sample, label=None, pad=None):
    lab = f' {chip(d, label, d["cyan"])}' if label else ""
    return (f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
            f'padding: {pad or d["pad"]}; display: flex; flex-direction: column; gap: 8px;">'
            f'<div style="display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap;">'
            f'<span style="font-family: {d["font_mono"]}; font-size: 11px; color: {side_color}; '
            f'letter-spacing: 1px;">{side_label}</span>{lab}</div>'
            f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h2"]};">{title}</div>'
            f'<div style="color: {d["mut"]};">{body}</div>'
            f'<div style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["faint"]};">{sample}</div>'
            f'</div>')

GAME_FACTORS = [
    ("LEANS PADRES", "cyan", "Cincinnati&rsquo;s right-handed core loses its platoon edge tonight",
     "The Reds&rsquo; three best bats hit right-handed and face a right-handed starter — the favorable split they had the last two nights is gone.",
     "sample: 402 plate appearances vs RHP this season", "Observation"),
    ("LEANS REDS", "red", "San Diego&rsquo;s bullpen worked both ends of a doubleheader Friday",
     "Five Padres relievers threw yesterday; the two highest-leverage arms threw 25+ pitches. A close game reaches a thinner pen than the season numbers suggest.",
     "sample: 9 relievers, 214 pitches over the last 3 days", "Observation"),
    ("PRICE", "amber", "Best Padres price is −130; the widest book is 29 cents worse",
     "Three books post −130 (BetOnline, Caesars, Lowvig); BetRivers posts −159. Same bet, meaningfully different number — this is line-shopping value, not a prediction.",
     "board of 11 books · updated 6:16 ET", None),
    ("CONTEXT", "mut", "Interesting matchup, but no demonstrated betting edge",
     "Nothing tonight clears the evidence bar this product holds itself to. The factors above are context for your own judgment, not a recommendation.",
     "27 pre-registered research hypotheses tested to date · zero survived", None),
]

# ---------------------------------------------------------------- TODAY -----
TODAY_GAMES = [
    ("Padres @ Reds", "6:41 ET", "SD 56.3% · CIN 43.7%",
     "Closest call tonight: Reds' right-heavy order faces a left-handed starter, but the sample behind the split is thin.",
     "consensus of 11 books", "cyan"),
    ("Tigers @ Twins", "7:41 ET", "DET 50.1% · MIN 49.9%",
     "The books disagree about the favorite — 7 price Detroit ahead, 4 price Minnesota. A genuine coin-flip board.",
     "widest book split on the slate", "amber"),
    ("Yankees @ Angels", "9:38 ET", "NYY 58.7% · LAA 41.3%",
     "69-cent spread on the away price (−117 to −186). Where you bet matters more than what you bet tonight.",
     "largest price spread", "amber"),
]

def _changed(d, pad=None):
    return (
      f'<div style="background: {d["panel2"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: 14px {pad or d["pad"]}; display: flex; gap: 18px; align-items: flex-start; flex-wrap: wrap;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; '
      f'color: {d["amber"]};">WHAT CHANGED</span>'
      f'<div style="display: flex; gap: 18px; flex-wrap: wrap; color: {d["mut"]}; font-size: {d["small"]}; flex: 1 1 260px;">'
      f'<span><span style="color: {d["text"]};">Lineups posted for 10 of 12 games</span> · latest 5:16 ET</span>'
      f'<span><span style="color: {d["text"]};">Books split on Tigers–Twins</span> · 4 of 11 books price Detroit as the underdog</span>'
      f'<span>Blue Jays optioned RHP C.J. Van Eyk · no game tonight affected</span>'
      f'</div></div>')

def _verdict(d, pad=None):
    return (
      f'<div style="padding: {pad or d["pad"]} 0 0; display: flex; flex-direction: column; gap: 6px;">'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h1"]};">'
      f'We checked all 12 games. Nothing clears the bar tonight.</div>'
      f'<div style="color: {d["mut"]}; max-width: 720px;">Every matchup was run through the full battery — '
      f'lineups, starters, bullpens, prices across 11 books. A quiet night is a finding, not a blank page. '
      f'The closest calls and the market context are below.</div></div>')

def _game_card(d, name, t, cons, note, tag, tagc, pad=None):
    return (
      f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: {pad or d["pad"]}; display: flex; flex-direction: column; gap: 10px;">'
      f'<div style="display: flex; justify-content: space-between; align-items: baseline;">'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h2"]};">{name}</div>'
      f'<span style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["faint"]};">{t}</span></div>'
      f'<div style="font-family: {d["font_mono"]}; font-size: 13px; color: {d["mut"]};">{cons} '
      f'<span style="color: {d["faint"]};">market-implied consensus</span></div>'
      f'<div style="color: {d["mut"]};">{note}</div>'
      f'<div>{chip(d, tag, d[tagc])}</div></div>')

def _price_note(d, pad=None):
    return (
      f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: {pad or d["pad"]}; color: {d["mut"]}; font-size: {d["small"]};">'
      f'<span style="color: {d["amber"]}; font-family: {d["font_mono"]}; font-size: 11px; '
      f'letter-spacing: 1.5px;">PRICES TONIGHT</span><br>'
      f'No board beats the market-implied consensus right now — normal, because a quoted price still carries '
      f'the book&rsquo;s margin and the consensus has had it removed. The best numbers on each side are in '
      f'<a href="#">Odds</a>.</div>')

def today(d, mobile=False):
    if mobile:
        cards = "".join(_game_card(d, *g, pad="16px") for g in TODAY_GAMES)
        inner = (f'<div style="display: flex; flex-direction: column; min-height: 1330px; background: {d["bg"]};">'
                 + mobile_head(d, "Today")
                 + f'<div style="display: flex; flex-direction: column; gap: 14px; padding: 14px 16px 28px;">'
                 + _changed(d, pad="16px") + _verdict(d, pad="4px") + cards + _price_note(d, pad="16px")
                 + '</div>' + tabbar(d, "Today") + '</div>')
        return shell(d, "Today mobile", inner)
    cards = "".join(_game_card(d, *g) for g in TODAY_GAMES)
    inner = (nav(d) + f'<div style="display: flex; flex-direction: column; gap: {d["gap"]}; padding: {d["gap"]} {d["pad"]} 40px;">'
             + _changed(d) + _verdict(d)
             + f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: {d["gap"]};">{cards}</div>'
             + _price_note(d) + '</div>')
    return shell(d, "Today", inner)

# ----------------------------------------------------------------- GAME -----
def _game_head(d, mobile=False):
    if mobile:
        return (f'<div style="padding: 14px 16px; border-bottom: {d["border"]};">'
                f'<div style="font-family: {d["font_mono"]}; font-size: 11px; color: {d["faint"]};">Sun Aug 31 · 6:41 ET · Great American Ball Park</div>'
                f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: 20px;">Padres @ Reds</div>'
                f'<div style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["mut"]}; margin-top: 4px;">SD 56.3% · CIN 43.7% '
                f'<span style="color: {d["faint"]};">market-implied consensus · 11 books</span></div></div>')
    return (
      f'<div style="padding: {d["pad"]}; display: flex; justify-content: space-between; align-items: flex-end; '
      f'border-bottom: {d["border"]};">'
      f'<div><div style="font-family: {d["font_mono"]}; font-size: 12px; color: {d["faint"]};">Sunday, August 31 · 6:41 ET · Great American Ball Park</div>'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h1"]};">San Diego Padres @ Cincinnati Reds</div></div>'
      f'<div style="text-align: right;"><div style="font-family: {d["font_mono"]}; font-size: 13px; color: {d["mut"]};">SD 56.3% · CIN 43.7%</div>'
      f'<div style="font-size: 11px; color: {d["faint"]};">market-implied consensus · 11 books</div></div></div>')

def _factors(d, pad=None):
    return "".join(factor(d, sl, d[sc], t, b, s, lab, pad=pad)
                   for sl, sc, t, b, s, lab in GAME_FACTORS)

def _adv_table(d, title, cols, rows, note):
    head = "".join(f'<div style="font-family: {d["font_mono"]}; font-size: 11px; color: {d["faint"]}; '
                   f'letter-spacing: 0.5px; text-align: {"left" if i==0 else "right"};">{c}</div>'
                   for i, c in enumerate(cols))
    body = ""
    for r in rows:
        body += (f'<div style="display: grid; grid-template-columns: 1.6fr repeat({len(cols)-1}, 1fr); gap: 8px; '
                 f'padding: 6px 0; border-bottom: 1px solid {d["line"]}55;">'
                 + "".join(f'<div style="font-family: {d["font_mono"] if i else d["font_body"]}; '
                           f'font-size: {d["small"]}; color: {d["text"] if i==0 else d["mut"]}; '
                           f'text-align: {"left" if i==0 else "right"};">{c}</div>'
                           for i, c in enumerate(r)) + '</div>')
    return (f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
            f'padding: {d["pad"]};">'
            f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h2"]}; '
            f'margin-bottom: 10px;">{title}</div>'
            f'<div style="display: grid; grid-template-columns: 1.6fr repeat({len(cols)-1}, 1fr); gap: 8px; '
            f'padding-bottom: 6px; border-bottom: {d["border"]};">{head}</div>'
            f'{body}'
            f'<div style="font-family: {d["font_mono"]}; font-size: 11px; color: {d["faint"]}; margin-top: 10px;">{note}</div></div>')

def _advanced_sections(d):
    splits = _adv_table(d, "Lineup vs starter — platoon splits",
        ["Reds hitter", "PA vs RHP", "wOBA vs RHP", "wOBA vs LHP"],
        [("E. De La Cruz", "402", ".356", ".312"),
         ("S. Steer", "377", ".341", ".305"),
         ("T. Friedl", "351", ".329", ".298"),
         ("J. India", "344", ".317", ".333"),
         ("Team (posted lineup)", "2,914", ".324", ".309")],
        "representative sample content · per-batter splits, 2026 season through Aug 30")
    pen = _adv_table(d, "Bullpen ledger — last 3 days",
        ["Padres reliever", "Pitches Fri", "Pitches Sat", "Available?"],
        [("R. Suárez (CL)", "27", "0", "likely"),
         ("J. Estrada", "25", "14", "doubtful"),
         ("A. Morejón", "18", "0", "yes"),
         ("W. Peralta", "0", "22", "likely"),
         ("Pen total (9 arms)", "118", "96", "6 of 9")],
        "representative sample content · availability is a heuristic, not team-announced")
    market = (f'<div style="background: {d["panel"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
              f'padding: {d["pad"]};">'
              f'<div style="display: flex; justify-content: space-between; margin-bottom: 10px; align-items: baseline;">'
              f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h2"]};">Full market board</div>'
              f'<span style="font-size: 11px; color: {d["faint"]};">11 books · updated 6:16 ET · best away price highlighted</span></div>'
              f'<div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; padding: 0 12px 6px; '
              f'font-family: {d["font_mono"]}; font-size: 11px; color: {d["faint"]};">'
              f'<div>Book</div><div style="text-align: right;">SD (away)</div><div style="text-align: right;">CIN (home)</div></div>'
              + board_rows(d, SD_CIN_BOARD) + '</div>')
    return (f'<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: {d["gap"]};">'
            f'{splits}{pen}</div>{market}')

def game(d, mobile=False, advanced=False):
    if mobile:
        inner = (f'<div style="display: flex; flex-direction: column; min-height: 1290px; background: {d["bg"]};">'
                 + mobile_head(d, "Padres @ Reds")
                 + f'<div style="display: flex; flex-direction: column; gap: 12px; padding: 12px 16px 28px;">'
                 + _game_head(d, mobile=True).replace('border-bottom', 'border-radius: 0; border-bottom')
                 + _factors(d, pad="16px")
                 + f'<div style="color: {d["faint"]}; font-size: {d["small"]}; text-align: center; padding: 6px 0;">'
                 f'Advanced — full splits, bullpen ledger, market board <span style="color: {d["cyan"]};">▾</span></div>'
                 + '</div>' + tabbar(d, "Games") + '</div>')
        return shell(d, "Game mobile", inner)
    adv_strip = (
      f'<div style="border-top: {d["border"]}; padding: {d["pad"]}; display: flex; align-items: center; gap: 12px;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; '
      f'color: {d["amber"] if advanced else d["faint"]};">ADVANCED</span>'
      f'<span style="color: {d["faint"]}; font-size: {d["small"]};">full splits, pitch mix, bullpen ledger, market table — '
      f'{"expanded below; the summary stays above" if advanced else "expands below, never replaces the summary"}</span>'
      f'<span style="margin-left: auto; color: {d["cyan"]};">{"Collapse ▴" if advanced else "Expand ▾"}</span></div>')
    inner = (nav(d, "Games") + _game_head(d)
             + f'<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: {d["gap"]}; padding: {d["gap"]} {d["pad"]};">{_factors(d)}</div>'
             + adv_strip)
    if advanced:
        inner += (f'<div style="display: flex; flex-direction: column; gap: {d["gap"]}; '
                  f'padding: 0 {d["pad"]} 40px;">{_advanced_sections(d)}</div>')
    return shell(d, "Game advanced" if advanced else "Game", inner)

# ------------------------------------------------------------- BET CHECK ----
def betcheck(d, mobile=False):
    pad = "16px" if mobile else d["pad"]
    your_bet = (
      f'<div style="background: {d["panel2"]}; border: {d["border"]}; border-radius: {d["radius"]}; '
      f'padding: {pad}; display: flex; flex-direction: column; gap: 6px;">'
      f'<span style="font-family: {d["font_mono"]}; font-size: 11px; letter-spacing: 1.5px; color: {d["faint"]};">YOUR BET</span>'
      f'<div style="font-family: {d["font_head"]}; font-weight: {d["headweight"]}; font-size: {d["h1"]};">Padres ML <span style="font-family: {d["font_mono"]};">−134</span></div>'
      f'<div style="color: {d["mut"]}; font-size: {d["small"]};">@ Reds · tonight 6:41 ET · price as entered</div></div>')
    support = factor(d, "SUPPORTS YOUR BET", d["cyan"],
      "The platoon math tilts your way",
      "Cincinnati&rsquo;s best hitters lose their left-right advantage against tonight&rsquo;s starter, and the consensus already makes your side a 56% favorite.",
      "sample: 402 PA vs RHP · consensus of 11 books", pad=pad)
    against = factor(d, "AGAINST YOUR BET", d["red"],
      "You are paying more than the best board price",
      "Three books post −130 for the same bet. At your −134, you give up 4 cents of price on identical risk — and San Diego&rsquo;s bullpen is short after Friday&rsquo;s doubleheader.",
      "board of 11 books · 9 relievers, 214 pitches / 3 days", pad=pad)
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
    if mobile:
        inner = (f'<div style="display: flex; flex-direction: column; min-height: 1240px; background: {d["bg"]};">'
                 + mobile_head(d, "Bet Check")
                 + f'<div style="display: flex; flex-direction: column; gap: 14px; padding: 14px 16px 28px;">'
                 + your_bet + support + against + market + bottom + '</div>'
                 + tabbar(d, "Bet Check") + '</div>')
        return shell(d, "Bet Check mobile", inner)
    inner = (nav(d, "Bet Check")
             + f'<div style="display: flex; flex-direction: column; gap: {d["gap"]}; padding: {d["gap"]} {d["pad"]} 40px;">'
             + your_bet
             + f'<div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: {d["gap"]};">{support}{against}</div>'
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
    howto = (f'<div style="background: {d["panel2"]}; border: {d["border"]}; border-radius: {d["radius"]}; padding: 22px;">'
             f'<div style="font-family: {d["font_mono"]}; font-size: 12px; letter-spacing: 1.5px; color: {d["cyan"]}; margin-bottom: 8px;">HOW TO REVIEW</div>'
             f'<div style="color: {d["mut"]};">Use the <b style="color: {d["text"]};">pages menu</b> (top of the canvas) — one page per direction. '
             f'Each direction page is a single vertical scroll of seven full-size views: Bet Check desktop, Bet Check phone, '
             f'Today desktop, Today phone, Game quick view, Game with Advanced expanded, Game phone. '
             f'The <b style="color: {d["text"]};">Bet Check Comparison</b> page puts all three directions side by side, desktop and phone, '
             f'if you want to compare the one screen that matters most before touring anything.</div></div>')
    inner = (f'<div style="max-width: 900px; margin: 0 auto; padding: 48px 40px; display: flex; '
             f'flex-direction: column; gap: 18px;">'
             f'<div style="font-family: {d["font_mono"]}; font-size: 12px; letter-spacing: 2px; color: {d["amber"]};">VISUAL DIRECTION DECISION</div>'
             f'<div style="font-family: {d["font_head"]}; font-weight: 600; font-size: 30px;">Three executions of the same product. Pick one.</div>'
             f'<div style="color: {d["mut"]};">Same information architecture, same evidence rules, same real slate '
             f'(Sunday, August 31 — odds as captured at 6:16 ET from 11 books). '
             f'Recommendation: <b style="color: {d["text"]};">Direction B (Terminal)</b> — '
             f'it owns the register no consumer competitor uses; A is the strongest alternative if it reads too cold.</div>'
             + howto + rows + '</div>')
    return shell(d, "Main", inner)

def comparison_note():
    d = DIRS["B"]
    diffs = [
        ("Type and register", "A sets the verdict and factor titles in a serif and gives everything room; B is one sans family, tighter, every number tabular; C uses a heavier display face, bigger radii, softer surfaces."),
        ("Density", "The same Bet Check runs tallest in A and tightest in B — B fits support + counterargument + price on one desktop screen with the least scrolling; C sits between."),
        ("Warmth vs authority", "C reads most like sports media (inviting, least differentiated); B reads most like a market terminal (authoritative, coldest); A is the broadsheet middle."),
    ]
    items = "".join(f'<div style="display: flex; flex-direction: column; gap: 4px;">'
                    f'<div style="font-family: {d["font_head"]}; font-weight: 600; font-size: 16px;">{t}</div>'
                    f'<div style="color: {d["mut"]};">{b}</div></div>' for t, b in diffs)
    inner = (f'<div style="padding: 30px 34px; display: flex; flex-direction: column; gap: 16px;">'
             f'<div style="font-family: {d["font_mono"]}; font-size: 12px; letter-spacing: 2px; color: {d["amber"]};">BET CHECK — WHAT ACTUALLY DIFFERS</div>'
             f'<div style="color: {d["mut"]};">Content is identical across A/B/C by design; only the execution varies. '
             f'Desktop row below, phone row beneath it. The three meaningful differences:</div>'
             + items + '</div>')
    return shell(d, "Comparison notes", inner)

# ------------------------------------------------------------------ emit ----
files = {"Main.dc.html": main_cover(), "CompareNotes.dc.html": comparison_note()}
for k, dd in DIRS.items():
    files[f"{k}BetCheck.dc.html"] = betcheck(dd)
    files[f"{k}BetCheckPhone.dc.html"] = betcheck(dd, mobile=True)
    files[f"{k}Today.dc.html"] = today(dd)
    files[f"{k}TodayPhone.dc.html"] = today(dd, mobile=True)
    files[f"{k}Game.dc.html"] = game(dd)
    files[f"{k}GameAdvanced.dc.html"] = game(dd, advanced=True)
    files[f"{k}GamePhone.dc.html"] = game(dd, mobile=True)
    # comparison-page duplicates (an artboard lives on exactly one page)
    files[f"Cmp{k}BetCheck.dc.html"] = betcheck(dd)
    files[f"Cmp{k}BetCheckPhone.dc.html"] = betcheck(dd, mobile=True)

for name, src in files.items():
    open(os.path.join(OUT, name), "w").write(src)

# ---- canvas: pages -----------------------------------------------------
boards = [{"file": "Main.dc.html", "x": 0, "y": 0, "w": 960, "h": 1360, "page": "start"}]

# per-direction vertical stacks: Bet Check first (priority), then mobile, etc.
VIEWS = [  # (suffix, title, w, h)
    ("BetCheck",      "Bet Check — desktop", 1240, 1000),
    ("BetCheckPhone", "Bet Check — phone 375px", 390, 1260),
    ("Today",         "Today — desktop", 1240, 960),
    ("TodayPhone",    "Today — phone 375px", 390, 1350),
    ("Game",          "Game — quick view desktop", 1240, 900),
    ("GameAdvanced",  "Game — Advanced expanded desktop", 1240, 2050),
    ("GamePhone",     "Game — phone 375px", 390, 1310),
]
for k in "ABC":
    y = 0
    page = f"dir-{k.lower()}"
    for suffix, title, w, h in VIEWS:
        boards.append({"file": f"{k}{suffix}.dc.html", "x": 0, "y": y, "w": w, "h": h,
                       "title": f"{DIRS[k]['name']} · {title}", "page": page})
        y += h + 160

# comparison page: notes, then desktop row, then phone row — full size
boards.append({"file": "CompareNotes.dc.html", "x": 0, "y": 0, "w": 1240, "h": 560, "page": "compare"})
x = 0
for k in "ABC":
    boards.append({"file": f"Cmp{k}BetCheck.dc.html", "x": x, "y": 720, "w": 1240, "h": 1000,
                   "title": f"{DIRS[k]['name']} · Bet Check desktop", "page": "compare"})
    x += 1340
x = 0
for k in "ABC":
    boards.append({"file": f"Cmp{k}BetCheckPhone.dc.html", "x": x, "y": 1900, "w": 390, "h": 1260,
                   "title": f"{DIRS[k]['name']} · Bet Check phone", "page": "compare"})
    x += 550

canvas = {
    "artboards": boards,
    "pages": [
        {"id": "start", "name": "START HERE"},
        {"id": "dir-a", "name": "A — Editorial"},
        {"id": "dir-b", "name": "B — Terminal"},
        {"id": "dir-c", "name": "C — Clubhouse"},
        {"id": "compare", "name": "Bet Check Comparison"},
    ],
    "annotations": [
        {"id": "start-note", "x": 1020, "y": 40, "w": 300,
         "text": "Pages menu → one page per direction (vertical scroll, full size).\n'Bet Check Comparison' = all three side by side.\nOdds and book names are real (captured 6:16 ET tonight).\nMatchup factor stats are representative sample content."}
    ],
    "launch": {"view": "canvas", "page": "start"},
}
open(os.path.join(OUT, "canvas.json"), "w").write(json.dumps(canvas, indent=1))
print("wrote", len(files), "artboards + canvas.json")
