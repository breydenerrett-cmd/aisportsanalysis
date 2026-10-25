"""The eleven topics of the interview, in order, and the form controls each one carries.

THE STATE MACHINE OWNS THE ORDER. A model may re-word a question; it never chooses which topic comes next,
skips one or ends the interview. Every topic below is a fixed question with fixed controls, and the controls
are what the web page draws in BOTH modes, so a person with the assistant resting fills in the same form.

Controls are plain dicts so the page can build them without knowing Python:

  {"name", "kind": "multi" | "single" | "price" | "number" | "short" | "text", "label", "options"?, ...}

A `single` or `multi` option may carry `unsupported: true`: it is listed so the person can say it, and choosing
it puts the idea under "can't automate yet" (never dropped, never silently turned into something else).

`text_slots` name the free-text boxes a topic has and what each one means to the reader:
  include   what must be true for the hound to bet (read by the deterministic English parser)
  exclude   things to skip (each line turned into the opposite condition, or refused)
  notes     kept with the record and scanned for ideas the language cannot run
"""

from __future__ import annotations

from typing import Dict, List

from src.hounds import user_rules as R
from src.hounds import user_spec
from src.hounds.interview import fields as F

TEXT_MAX = 600
EXAMPLE_MAX = 160
EXAMPLES_MAX = 5

# (id, label, supported, condition ids or the reason it cannot be used)
DATA_CHOICES = (
    ("weather", "Weather: temperature, wind, rain, roof (MLB)", True, ("temperature", "wind_speed", "rain_chance", "roof")),
    ("rest", "Rest days and travel", True, ("rest_days", "travel_miles")),
    ("form", "Recent form and streaks", True, ("streak", "last_n_wins")),
    ("h2h", "Head-to-head meetings", True, ("head_to_head",)),
    ("home_road", "Home and road records", True, ("venue_record", "split_pct")),
    ("scoring", "Scoring, defense and league rank", True, ("scoring_rate", "league_rank", "matchup_edge")),
    ("line_move", "Line movement since our first capture", True, ("steam",)),
    ("schedule", "Day of week and time of day", True, ("day_of_week", "time_of_day")),
    ("teams", "Specific teams or players", True, ("team_is", "opponent_is", "player_is")),
    ("player_form", "Player hit and strikeout form (MLB props)", True, ("player_streak", "player_form", "player_rate")),
    ("injuries", "Injuries", False, "Injuries are not available to the rules yet."),
    ("starters", "Starting pitchers, goalies or quarterbacks", False,
     "Starting pitchers, goalies, quarterbacks, lineups and bullpens are not available to the rules yet."),
    ("public", "Public betting percentages or sharp money", False,
     "Public betting percentages, money splits and sharp-money signals are not available to the rules."),
    ("open_close", "The opening or closing line", False,
     "A hound is priced at its lock time, as the average across books. It cannot take the opening or the closing line."),
    ("gematria", "Gematria or custom calculations", False,
     "Only the menu's own numerology condition exists. Custom gematria calculations are not available."),
    ("milestones", "Historical milestones", False, "Milestones, anniversaries and storylines are not facts the rules can read."),
)
DATA_BY_ID = {row[0]: row for row in DATA_CHOICES}

UNSUPPORTED_MARKETS = (
    ("f5", "First five innings, halves and quarters", "First-five-innings, half and quarter markets are not on the menu."),
    ("parlay", "Parlays and teasers", "Parlays, teasers, futures and alternate lines are not on the menu. A hound makes single paper bets."),
)
UNSUPPORTED_MARKET_BY_ID = {row[0]: row for row in UNSUPPORTED_MARKETS}


def _opts(pairs) -> List[dict]:
    return [{"value": v, "label": label} for v, label in pairs]


def _text(name: str, label: str, role: str, *, help: str = "", maximum: int = TEXT_MAX, rows: int = 3,
          placeholder: str = "") -> dict:
    return {"name": name, "kind": "text", "label": label, "role": role, "max": maximum, "rows": rows,
            "help": help, "placeholder": placeholder}


def _sports_options() -> List[dict]:
    return [{"value": s["value"], "label": s["label"]} for s in user_spec.sports_menu()]


def _market_options() -> List[dict]:
    out = []
    for m in R.ALL_MARKETS:
        label = R.MARKET_LABELS[m]
        out.append({"value": m, "label": label + (f" ({' / '.join(R.prop_sports(m))})" if R.market_kind(m) == "prop" else "")})
    out += [{"value": f"x:{mid}", "label": label, "unsupported": True} for mid, label, _ in UNSUPPORTED_MARKETS]
    return out


def _price_presets() -> List[int]:
    return sorted(set(user_spec.PRICE_PRESETS_SHORT) | set(user_spec.PRICE_PRESETS_LONG),
                  key=lambda p: user_spec.price_decimal(p))


def build_topics() -> List[dict]:
    """The topics with their controls. Built on call so the sport menu is whatever the catalog says today."""
    prices = _price_presets()
    return [
        {"id": "scope", "title": "Sports and markets",
         "prompt": "Which sports and which bets should this hound make, and does it bet before the game or live?",
         "required": ("sports", "markets", "timing"), "skippable": False,
         "controls": [
             {"name": "sports", "kind": "multi", "label": "Sports", "options": _sports_options()},
             {"name": "markets", "kind": "multi", "label": "Bets", "options": _market_options()},
             {"name": "timing", "kind": "single", "label": "When it bets",
              "options": [{"value": "pregame", "label": "Before the game"},
                          {"value": "live", "label": "Live, during the game", "unsupported": True},
                          {"value": "both", "label": "Both", "unsupported": True}]},
             _text("text", "Anything to add, in your own words", "include", rows=2,
                   placeholder="e.g. MLB totals and run lines, never live")]},
        {"id": "side", "title": "Side and triggers",
         "prompt": "Which side does it take, and what has to be true before it bets? Add anything it should skip.",
         "required": ("side",), "skippable": False,
         "controls": [
             {"name": "side", "kind": "single", "label": "Which side",
              "options": _opts([("either", "Either side, the conditions decide"), ("home", "The home side"),
                                ("away", "The away side"), ("over", "The over"), ("under", "The under")])},
             {"name": "role", "kind": "single", "label": "Favourite or underdog",
              "options": _opts([("any", "Either"), ("favourite", "Favourites only"), ("underdog", "Underdogs only")])},
             _text("text", "What has to be true to bet", "include",
                   help="Plain sentences. One idea per sentence reads best.",
                   placeholder="e.g. The team has at least 2 days of rest and the wind is under 10 mph."),
             _text("exclude_text", "What to skip, one per line", "exclude",
                   help="Each line is turned into a rule that skips those games.",
                   placeholder="e.g. Skip when the forecast chance of rain is over 50%.")]},
        {"id": "price", "title": "Odds, books and line timing",
         "prompt": "What prices will it take, how many books must be quoting it, and when is the price read?",
         "required": (), "skippable": False,
         "controls": [
             {"name": "price_any", "kind": "single", "label": "Price range",
              "options": [{"value": True, "label": "Any price (never -200 or worse)"},
                          {"value": False, "label": "Only between two prices"}]},
             {"name": "price_min", "kind": "price", "label": "Shortest price", "presets": prices,
              "lowest": user_spec.SHORTEST_ALLOWED_PRICE, "highest": user_spec.LONGEST_ALLOWED_PRICE},
             {"name": "price_max", "kind": "price", "label": "Longest price", "presets": prices,
              "lowest": user_spec.SHORTEST_ALLOWED_PRICE, "highest": user_spec.LONGEST_ALLOWED_PRICE},
             {"name": "min_books", "kind": "number", "label": "Books quoting it, at least",
              "min": user_spec.MIN_BOOKS_RANGE[0], "max": user_spec.MIN_BOOKS_RANGE[1]},
             {"name": "line_timing", "kind": "single", "label": "When the price is read",
              "options": [{"value": "lock", "label": "At the lock, as the average across books"},
                          {"value": "opening", "label": "The opening line", "unsupported": True},
                          {"value": "closing", "label": "The closing line", "unsupported": True}]},
             _text("text", "Books or price notes", "include", rows=2,
                   placeholder="e.g. Underdogs from +110 to +250. Only at one book.")]},
        {"id": "data", "title": "Data it needs",
         "prompt": "What information does the strategy rely on? Tick what applies. Anything a hound cannot use yet is listed, not dropped.",
         "required": (), "skippable": True,
         "controls": [{"name": "data", "kind": "multi", "label": "Information used",
                       "options": [{"value": d[0], "label": d[1], "unsupported": not d[2]} for d in DATA_CHOICES]},
                      _text("text", "Anything else it needs", "notes", rows=2)]},
        {"id": "examples", "title": "Examples",
         "prompt": "Give one or two games it would bet and one or two it would not. They are kept with the record and never used to tune it.",
         "required": (), "skippable": True,
         "controls": [_text("trigger_text", "Games it would bet, one per line", "examples", maximum=EXAMPLE_MAX * EXAMPLES_MAX, rows=3),
                      _text("skip_text", "Games it would not bet, one per line", "examples", maximum=EXAMPLE_MAX * EXAMPLES_MAX, rows=3)]},
        {"id": "pass_rules", "title": "When to pass",
         "prompt": "When should it pass? Describe any other game to skip. If a fact it needs is missing or stale, it always passes and says why.",
         "required": (), "skippable": True,
         "controls": [_text("exclude_text", "Pass when, one per line", "exclude",
                            placeholder="e.g. Pass when the market has moved against the pick.")]},
        {"id": "limits", "title": "Daily limit and lock time",
         "prompt": "How many bets a day at most, and how long before the start does it lock?",
         "required": ("max_bets_per_day", "lock_minutes"), "skippable": False,
         "controls": [{"name": "max_bets_per_day", "kind": "number", "label": "Most bets a day",
                       "min": user_spec.MAX_BETS_RANGE[0], "max": user_spec.MAX_BETS_RANGE[1]},
                      {"name": "lock_minutes", "kind": "single", "label": "Locks before the start",
                       "options": [{"value": m, "label": f"{m} minutes"} for m in user_spec.LOCK_CHOICES]}]},
        {"id": "stake", "title": "Stake",
         "prompt": "How big is each paper bet? Every bet is one flat stake.",
         "required": ("stake_units",), "skippable": False,
         "controls": [{"name": "stake_units", "kind": "single", "label": "Paper units per bet",
                       "options": [{"value": s, "label": f"{s:g} unit" + ("" if s == 1 else "s")} for s in R.STAKE_CHOICES]},
                      _text("text", "Exposure limits or stop rules", "notes", rows=2,
                            help="Anything beyond a flat stake is listed as not available yet.")]},
        {"id": "history", "title": "Dated history (optional)",
         "prompt": "Optional. Paste or upload dated results you have kept. They are kept as claimed and unverified and never count toward the hound's record.",
         "required": (), "skippable": True,
         "controls": [_text("text", "One result per line: date, pick, price, result", "history", maximum=40_000, rows=6,
                            placeholder="2026-09-03, Cubs ML, +120, W")]},
        {"id": "disprove", "title": "What would prove it wrong",
         "prompt": "What result would tell you this strategy does not work?",
         "required": (), "skippable": True,
         "controls": [_text("text", "In your words", "notes", rows=3)]},
        {"id": "publish", "title": "Showing your strategy",
         "prompt": "May we show your strategy notes and your name next to the hound? Every hound's rule and bets are public either way.",
         "required": ("publish_ok",), "skippable": False,
         "controls": [{"name": "publish_ok", "kind": "single", "label": "Show my notes",
                       "options": [{"value": True, "label": "Yes, show them"}, {"value": False, "label": "No, keep them private"}]},
                      {"name": "attribution", "kind": "single", "label": "Credit me as",
                       "options": _opts([("anonymous", "Anonymous"), ("kennel", "My kennel name"), ("named", "A name I type")])},
                      {"name": "attribution_name", "kind": "short", "label": "The name to show", "max": 40}]},
    ]


def topic_ids() -> List[str]:
    return [t["id"] for t in build_topics()]


_BY_ID: Dict[str, dict] = {}


def get(topic_id: str) -> dict:
    if not _BY_ID:
        _BY_ID.update({t["id"]: t for t in build_topics()})
    return _BY_ID[topic_id]


def control_names(topic_id: str) -> tuple:
    return tuple(c["name"] for c in get(topic_id)["controls"] if c["kind"] != "text")


def text_slots(topic_id: str) -> Dict[str, str]:
    """{slot name: role} for the topic's free-text boxes."""
    return {c["name"]: c["role"] for c in get(topic_id)["controls"] if c["kind"] == "text"}


def field_names(topic_id: str) -> tuple:
    """The fields a topic's controls set (selection controls only; `data` is a list of data choices)."""
    return tuple(n for n in control_names(topic_id) if n in F.KNOWN)


def all_known_fields_for(topic_id: str) -> tuple:
    return field_names(topic_id)
