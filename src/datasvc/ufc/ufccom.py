"""UFC.com career profiles: which slugs to try, a page parser, and a fetcher that will not store
a page under the wrong fighter. Fills `ufccom_profiles.jsonl` (key `fighter_id`).

WARNING FOR EVERY CONSUMER: the page shows career totals AS OF THE DAY IT WAS FETCHED. It has
no history, so these figures are not point-in-time safe. Use them for "how does this fighter
look now" (an upcoming bout), never as a feature of a bout that has already happened. The
`fetched_utc` on the record is the as-of time.

What is UFC-only and what is not. Strikes, takedowns, submissions, knockdowns, accuracy,
defence, average fight time and the by-position and by-target splits are computed over the
fighter's UFC fights. The record and the win counts (wins_ko, wins_sub, wins_dec) are the whole
professional career: Lucas Armand has no UFC fight yet and shows 6-0-0 with 5 KO wins.

Page elements each value comes from (class names are UFC.com's; `#athlete-stats` is the stats
section, the bio sits in the tabs below it):

* page_name           h1.hero-profile__name
* page_nickname       p.hero-profile__nickname, the quotation marks removed
* page_division       p.hero-profile__division-title, without " Division"
* page_status         bio field "Status" (.c-bio__field), else a hero tag (.hero-profile__tag)
                      that says Active, Retired or Not Fighting. Some pages have neither.
* ufc_slug            the last path segment of <link rel="canonical">. This is the real slug
                      even when the page was reached through an alias: /athlete/bruno-silva-0
                      is canonically /athlete/bruno-silva-blindado.
* record_text         p.hero-profile__division-body, as shown ("25-8-0 (W-L-D)")
* record              {"wins", "losses", "draws"} read out of record_text
* wins_ko, wins_dec, wins_sub
                      "Win by Method" (.c-stat-3bar): KO/TKO, DEC, SUB, the count before the
                      bracket. Falls back to the hero stats "Wins by Knockout" and "Wins by
                      Submission" when the method block is missing. A page may show only some
                      hero stats (Armand has no submissions one); the method block always
                      has all three, so wins_sub is 0 there, not null.
* first_round_finishes, title_defenses
                      the hero stats (.hero-profile__stat) or .athlete-stats__stat of the same
                      names. A page shows "Title Defenses" in place of the first, or neither.
* sig_str_landed_per_min, sig_str_absorbed_per_min
                      .c-stat-compare__group labelled "Sig. Str. Landed" / "Sig. Str.
                      Absorbed" with suffix "Per Min"
* takedown_avg_per_15, submission_avg_per_15
                      groups "Takedown avg" / "Submission avg", suffix "Per 15 Min"
* sig_str_defense_pct, takedown_defense_pct
                      groups "Sig. Str. Defense" / "Takedown Defense" (a percentage, 0 to 100)
* knockdown_avg_per_15
                      group "Knockdown Avg" (the page's tooltip: per 15 minutes)
* avg_fight_time_s    group "Average fight time", "13:04", as seconds (784)
* sig_str_accuracy_pct, sig_str_landed, sig_str_attempted
                      the "Striking accuracy" block (.overlap-athlete-content): the circle's
                      percentage (text.e-chart-circle__percent) and its Sig. Strikes Landed
                      and Sig. Strikes Attempted rows (dl.c-overlap__stats)
* takedown_accuracy_pct, takedowns_landed, takedowns_attempted
                      the "Takedown Accuracy" block, same layout
* sig_str_standing, sig_str_clinch, sig_str_ground (+ the same names with _pct)
                      "Sig. Str. By Position" (.c-stat-3bar): "266 (79%)" is 266 strikes, 79%
* sig_str_head, sig_str_body, sig_str_leg (+ _pct)
                      "Sig. Str. by target": the SVG text elements with ids
                      e-stat-body_x5F__x5F_{head,body,leg}_{value,percent}
* place_of_birth, trains_at, fighting_style, octagon_debut (ISO date), ufc_height_in,
  ufc_weight_lb, ufc_reach_in, ufc_leg_reach_in
                      the bio fields (.c-bio__label / .c-bio__text). These are UFC.com's own
                      numbers, not ESPN's, and they differ (Naurdiev is 72 in on UFC.com and 70
                      on ESPN), hence the ufc_ prefix: they never overwrite a `fighters` field.
* other_figures       any labelled figure on the page that is not in the list above, by label
                      (also a known label whose unit suffix changed: never filed under the
                      wrong name)
* notes               what the parser had to decide, as text. Empty on a clean page. It is also
                      the tripwire for a layout change: a page that names an athlete but holds
                      none of the known figure blocks says so here instead of parsing silently
                      to nothing.

Fields are null when the page does not show them. Two things the page prints that are not
measurements are turned into null (and noted), because a printed zero reads as a real one:

* An UFC figure block that shows only placeholder zeros ("0 (0 %)", "00:00"), as for a
  fighter with no UFC fight. Every UFC-only figure is null for that page.
* An accuracy of 0% whose landed count is blank. Naurdiev's page shows "Takedown Accuracy 0%"
  with Takedowns Landed empty, Takedowns Attempted 22 and a takedown average of 1.48: the 0% is
  how the page draws a missing number, so takedown_accuracy_pct is null.

Fields added to the contract (UFC_SCHEMA.md lists only the career figures): matched_on, the
bio and identity fields above, the counts behind each percentage, first_round_finishes,
title_defenses, the by-position and by-target splits, other_figures and notes.

Identity, and why a 404 is not what a missing page looks like. UFC.com does not answer 404 for
a slug it does not have. Seen live on 2026-10-03: /athlete/qqzx-notarealperson is HTTP 200 with
the site's search-results page (canonical /search), and /athlete/ismail-naurdiev-0 is HTTP 200
with a different fighter, Isaac Vallie-Flagg (w2_athlete_isaac-vallie-flagg.html, w2_search_
results_unknown_slug.html). So a page is accepted only if it is verifiably this fighter:

* its name matches (`names.match` over the fighter's aliases), and
* when both sides have a record, the two are within RECORD_TOLERANCE results of each other (one
  fight of lag between two sites, plus a margin). A name alone is not enough:
  /athlete/bruno-silva (flyweight, 15-9-2) and /athlete/bruno-silva-blindado (middleweight,
  23-13-0) are two men with one name; the second is also reachable as /athlete/bruno-silva-0.

Otherwise the next slug is tried, and if none fits the answer is None. A missing profile is a
null; a wrong profile is a wrong feature. A real 404 is handled the same way as any other
non-match, and `lookup_profile` reports what each slug turned out to be.

The fetcher caches a 200 forever unless `max_age_s` is given, and the search page for a missing
athlete is a 200: pass `max_age_s` when fetching profiles, or a fighter whose page does not exist
yet (a new signing) stays "missing" in the cache after UFC.com creates it. UFC.com is slower
than ESPN to be polite to: use a fetcher with delay_s of a second or more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

from src.datasvc import names
from src.datasvc.http import NotFound, PoliteFetcher
from src.datasvc.ufc import espn_urls, fighters

RECORD_TOLERANCE = 2
MAX_SLUG_CANDIDATES = 8

# Every figure `parse_profile` returns, in order, with identity and bio fields around them.
FIGURE_FIELDS = (
    "wins_ko", "wins_sub", "wins_dec", "first_round_finishes", "title_defenses",
    "sig_str_landed_per_min", "sig_str_absorbed_per_min", "sig_str_accuracy_pct", "sig_str_defense_pct",
    "sig_str_landed", "sig_str_attempted",
    "takedown_avg_per_15", "takedown_accuracy_pct", "takedown_defense_pct",
    "takedowns_landed", "takedowns_attempted",
    "submission_avg_per_15", "knockdown_avg_per_15", "avg_fight_time_s",
    "sig_str_standing", "sig_str_standing_pct", "sig_str_clinch", "sig_str_clinch_pct",
    "sig_str_ground", "sig_str_ground_pct",
    "sig_str_head", "sig_str_head_pct", "sig_str_body", "sig_str_body_pct", "sig_str_leg", "sig_str_leg_pct",
)
BIO_FIELDS = ("place_of_birth", "trains_at", "fighting_style", "octagon_debut",
              "ufc_height_in", "ufc_weight_lb", "ufc_reach_in", "ufc_leg_reach_in")
PROFILE_FIELDS = (("page_name", "page_nickname", "page_division", "page_status", "ufc_slug",
                   "record_text", "record") + FIGURE_FIELDS + BIO_FIELDS + ("other_figures", "notes"))

# Figures that exist only if the fighter has a UFC fight (see the module docstring).
UFC_ONLY_FIELDS = tuple(f for f in FIGURE_FIELDS if f not in
                        ("wins_ko", "wins_sub", "wins_dec", "first_round_finishes", "title_defenses"))


# -- a small DOM on html.parser ---------------------------------------------------------

_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                        "param", "source", "track", "wbr"})
_RAW_TEXT_TAGS = frozenset({"script", "style"})


class _Node:
    """An element: its tag, attributes, and children (nodes and text, in document order)."""

    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: Dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list = []

    def classes(self) -> List[str]:
        return self.attrs.get("class", "").split()

    def descendants(self) -> Iterator["_Node"]:
        """Every element below this one, in document order (iterative: a bad page cannot recurse us out)."""
        stack = [iter(self.children)]
        while stack:
            for child in stack[-1]:
                if isinstance(child, _Node):
                    yield child
                    stack.append(iter(child.children))
                    break
            else:
                stack.pop()

    def find_all(self, tag: Optional[str] = None, cls: Optional[str] = None) -> Iterator["_Node"]:
        for node in self.descendants():
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and cls not in node.classes():
                continue
            yield node

    def find(self, tag: Optional[str] = None, cls: Optional[str] = None) -> Optional["_Node"]:
        return next(self.find_all(tag, cls), None)

    def text(self) -> str:
        """All text below this element, whitespace collapsed to single spaces."""
        parts: List[str] = []
        stack = [iter(self.children)]
        while stack:
            for child in stack[-1]:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    stack.append(iter(child.children))
                    break
            else:
                stack.pop()
        return " ".join("".join(parts).split())


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("[document]", {})
        self._stack: List[_Node] = [self.root]

    def _open(self, tag: str, attrs) -> _Node:
        node = _Node(tag, {k: (v if v is not None else "") for k, v in attrs})
        self._stack[-1].children.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._open(tag, attrs)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):     # close back to the matching open tag
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if self._stack[-1].tag not in _RAW_TEXT_TAGS:
            self._stack[-1].children.append(data)


def _parse_document(html) -> _Node:
    if html is None:
        html = ""
    if isinstance(html, (bytes, bytearray)):
        html = bytes(html).decode("utf-8", "replace")
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


# -- value readers ----------------------------------------------------------------------

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_DURATION = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_COUNT_PCT = re.compile(r"^\s*(\d[\d,]*)\s*\(\s*(\d+(?:\.\d+)?)\s*%?\s*\)\s*$")
_RECORD = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
_US_DATE = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})$")
_TARGET_ID = re.compile(r"^e-stat-body(?:_x5F_|_)+(head|body|leg)_(value|percent)$")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"), 1)}
_STATUSES = {"active": "Active", "retired": "Retired", "not fighting": "Not Fighting"}


def _key(text: Optional[str]) -> str:
    """A label as a comparison key: lower case, single spaces, no trailing colon."""
    return " ".join((text or "").lower().split()).rstrip(": ")


def _number(text: Optional[str]):
    """The first number in `text`: an int when written without a decimal point; None if there is none."""
    match = _NUMBER.search((text or "").replace(",", ""))
    if not match:
        return None
    raw = match.group(0)
    return float(raw) if "." in raw else int(raw)


def _duration_s(text: Optional[str]) -> Optional[int]:
    match = _DURATION.match((text or "").strip())
    if not match:
        return None
    first, second, third = match.groups()
    if third is not None:                                  # h:mm:ss
        return int(first) * 3600 + int(second) * 60 + int(third)
    return int(first) * 60 + int(second)                  # m:ss


def _count_and_pct(text: Optional[str]) -> Tuple[Optional[int], Optional[float]]:
    """Read "266 (79%)" as (266, 79) and "0 (0 %)" as (0, 0); a bare count gives (count, None)."""
    match = _COUNT_PCT.match(text or "")
    if match:
        pct = float(match.group(2))
        return int(match.group(1).replace(",", "")), (int(pct) if pct == int(pct) else pct)
    number = _number(text)
    return (number if isinstance(number, int) else None), None


def _us_date(text: Optional[str]) -> Optional[str]:
    match = _US_DATE.match((text or "").strip())
    if not match:
        return None
    month = _MONTHS.get(match.group(1)[:3].lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(2))).isoformat()
    except ValueError:
        return None


def _positive(text: Optional[str]):
    number = _number(text)
    return number if number is not None and number > 0 else None


def _text_or_none(node: Optional[_Node]) -> Optional[str]:
    return (node.text() or None) if node is not None else None


# -- parse_profile ----------------------------------------------------------------------

# (label, unit suffix) of a .c-stat-compare__group -> field. A label with a suffix the table
# does not list is a different unit, so it goes to other_figures instead of a field.
_COMPARE = {
    "sig. str. landed": ("sig_str_landed_per_min", ("per min",)),
    "sig. str. absorbed": ("sig_str_absorbed_per_min", ("per min",)),
    "takedown avg": ("takedown_avg_per_15", ("per 15 min",)),
    "submission avg": ("submission_avg_per_15", ("per 15 min",)),
    "sig. str. defense": ("sig_str_defense_pct", ("",)),
    "takedown defense": ("takedown_defense_pct", ("",)),
    "knockdown avg": ("knockdown_avg_per_15", ("", "per 15 min")),
    "average fight time": ("avg_fight_time_s", ("",)),
}
_HERO_STATS = {
    "wins by knockout": "wins_ko", "wins by submission": "wins_sub", "wins by decision": "wins_dec",
    "first round finishes": "first_round_finishes", "title defenses": "title_defenses",
}
_METHOD_BAR = {"ko/tko": "wins_ko", "dec": "wins_dec", "sub": "wins_sub"}
_POSITION_BAR = {"standing": "sig_str_standing", "clinch": "sig_str_clinch", "ground": "sig_str_ground"}
_OVERLAP = {
    "striking accuracy": ("sig_str_accuracy_pct", {"sig. strikes landed": "sig_str_landed",
                                                   "sig. strikes attempted": "sig_str_attempted"}),
    "takedown accuracy": ("takedown_accuracy_pct", {"takedowns landed": "takedowns_landed",
                                                    "takedowns attempted": "takedowns_attempted"}),
}
_BIO = {"place of birth": "place_of_birth", "trains at": "trains_at", "fighting style": "fighting_style"}
_BIO_NUMBERS = {"height": "ufc_height_in", "weight": "ufc_weight_lb", "reach": "ufc_reach_in",
                "leg reach": "ufc_leg_reach_in"}


def _canonical_slug(root: _Node) -> Optional[str]:
    for link in root.find_all("link"):
        if "canonical" in link.attrs.get("rel", "").lower().split():
            parts = [p for p in urlsplit(link.attrs.get("href", "")).path.split("/") if p]
            if len(parts) >= 2 and parts[-2] == "athlete":
                return parts[-1].lower()
    return None


def parse_profile(html) -> dict:
    """Every career figure one UFC.com athlete page shows, as numbers. Pure: no network, no clock.

    Returns a dict with exactly the keys in PROFILE_FIELDS (identity and bio fields, the career
    figures, `other_figures` and `notes`); what the page does not show is None. A page that is
    not an athlete page parses to all None with page_name None. See the module docstring for the
    page element behind each value and for the two kinds of printed placeholder that become null.
    """
    root = _parse_document(html)
    scope = next((n for n in root.descendants() if n.attrs.get("id") == "athlete-stats"), root)
    fig: Dict[str, object] = {name: None for name in FIGURE_FIELDS}
    other: Dict[str, object] = {}
    notes: List[str] = []

    # Hero: identity, record text and the three or four headline counts.
    page_name = _text_or_none(root.find("h1", "hero-profile__name"))
    nickname = _text_or_none(root.find(cls="hero-profile__nickname"))
    if nickname:
        nickname = nickname.strip("\"'“”‘’ ") or None
    division = _text_or_none(root.find(cls="hero-profile__division-title"))
    if division and division.lower().endswith(" division"):
        division = division[:-len(" division")].strip()
    record_text = _text_or_none(root.find(cls="hero-profile__division-body"))
    match = _RECORD.match(record_text or "")
    record = ({"wins": int(match.group(1)), "losses": int(match.group(2)), "draws": int(match.group(3))}
              if match else None)

    def file_stat(label: str, value) -> None:
        field_name = _HERO_STATS.get(_key(label))
        if field_name is not None:
            fig[field_name] = value
        elif label:
            other[label] = value

    for node in root.find_all(cls="hero-profile__stat"):
        label = _text_or_none(node.find(cls="hero-profile__stat-text")) or ""
        file_stat(label, _number(_text_or_none(node.find(cls="hero-profile__stat-numb"))))
    for node in scope.find_all(cls="athlete-stats__stat"):
        label = _text_or_none(node.find(cls="athlete-stats__stat-text")) or ""
        file_stat(label, _number(_text_or_none(node.find(cls="athlete-stats__stat-numb"))))

    blocks_seen = 0      # figure blocks found, filled or blank: zero on an athlete page means the layout moved

    # Accuracy blocks: a percentage in a circle and two counts underneath.
    for block in scope.find_all(cls="overlap-athlete-content"):
        blocks_seen += 1
        title = _key(_text_or_none(block.find("h2")))
        pct_node = block.find("text", "e-chart-circle__percent")
        pct = _number(_text_or_none(pct_node))
        if pct is None:
            pct = _number(_text_or_none(block.find("title")))
        pct_field, count_fields = _OVERLAP.get(title, (None, {}))
        if pct_field is not None:
            fig[pct_field] = pct
        elif title:
            other[title] = pct
        for dl in block.find_all("dl"):
            label = _key(_text_or_none(dl.find("dt")))
            value = _number(_text_or_none(dl.find("dd")))
            if label in count_fields:
                fig[count_fields[label]] = value
            elif label:
                other[label] = value

    # Paired comparison figures ("3.66 Sig. Str. Landed Per Min").
    for group in scope.find_all(cls="c-stat-compare__group"):
        blocks_seen += 1
        label = _text_or_none(group.find(cls="c-stat-compare__label")) or ""
        suffix = _text_or_none(group.find(cls="c-stat-compare__label-suffix")) or ""
        number_text = _text_or_none(group.find(cls="c-stat-compare__number"))
        target = _COMPARE.get(_key(label))
        if target is not None and _key(suffix) in target[1]:
            field_name = target[0]
            fig[field_name] = _duration_s(number_text) if field_name == "avg_fight_time_s" else _number(number_text)
        elif label:
            is_time = ":" in (number_text or "")
            other[f"{label} {suffix}".strip()] = _duration_s(number_text) if is_time else _number(number_text)

    # Three-way bars: strikes by position, wins by method.
    for bar in scope.find_all(cls="c-stat-3bar"):
        blocks_seen += 1
        title = _key(_text_or_none(bar.find(cls="c-stat-3bar__title")))
        for group in bar.find_all(cls="c-stat-3bar__group"):
            label = _key(_text_or_none(group.find(cls="c-stat-3bar__label")))
            count, pct = _count_and_pct(_text_or_none(group.find(cls="c-stat-3bar__value")))
            if title == "sig. str. by position" and label in _POSITION_BAR:
                fig[_POSITION_BAR[label]] = count
                fig[_POSITION_BAR[label] + "_pct"] = pct
            elif title == "win by method" and label in _METHOD_BAR:
                field_name = _METHOD_BAR[label]
                if fig[field_name] is not None and fig[field_name] != count:
                    notes.append(f"{field_name}: hero says {fig[field_name]}, Win by Method says {count}; "
                                 f"kept {count}")
                fig[field_name] = count
            elif label:
                other[f"{title}: {label}"] = count

    # Strikes by target: SVG text elements named by id.
    for node in scope.find_all("text"):
        target_match = _TARGET_ID.match(node.attrs.get("id", ""))
        if target_match:
            blocks_seen += 1
            part, kind = target_match.groups()
            fig[f"sig_str_{part}" + ("" if kind == "value" else "_pct")] = _number(node.text())

    if page_name and blocks_seen == 0:
        notes.append("the page names an athlete but holds none of the known figure blocks: it has no stats "
                     "section, or UFC.com changed its layout")

    # The two printed placeholders (see the module docstring).
    present = [fig[f] for f in UFC_ONLY_FIELDS if fig[f] is not None]
    if not any(present):
        if present:
            notes.append("no UFC fight data: every UFC figure on the page is a placeholder zero, all set to null")
        else:
            notes.append("no UFC fight data: the page shows no UFC figures")
        for name in UFC_ONLY_FIELDS:
            fig[name] = None
    else:
        for pct_field, count_field in (("sig_str_accuracy_pct", "sig_str_landed"),
                                       ("takedown_accuracy_pct", "takedowns_landed")):
            if fig[pct_field] == 0 and fig[count_field] is None:
                fig[pct_field] = None
                notes.append(f"{pct_field}: the page shows 0% but {count_field} is blank, so the 0% is "
                             f"not a measurement; set to null")
        notes.extend(_consistency_notes(fig, record))

    # Bio.
    bio_scope = root.find(cls="c-bio--athlete") or root
    bio: Dict[str, str] = {}
    for node in bio_scope.find_all(cls="c-bio__field"):
        label, value = node.find(cls="c-bio__label"), node.find(cls="c-bio__text")
        if label is not None and value is not None:
            bio[_key(label.text())] = value.text()
    out_bio: Dict[str, object] = {name: None for name in BIO_FIELDS}
    for label, field_name in _BIO.items():
        out_bio[field_name] = fighters.clean_text(bio.get(label))
    for label, field_name in _BIO_NUMBERS.items():
        out_bio[field_name] = _positive(bio.get(label))
    out_bio["octagon_debut"] = _us_date(bio.get("octagon debut"))

    status = fighters.clean_text(bio.get("status"))
    if status is None:
        status = next((_STATUSES[_key(t.text())] for t in root.find_all(cls="hero-profile__tag")
                       if _key(t.text()) in _STATUSES), None)

    out: Dict[str, object] = {
        "page_name": page_name, "page_nickname": nickname, "page_division": division,
        "page_status": status, "ufc_slug": _canonical_slug(root),
        "record_text": record_text, "record": record,
    }
    out.update(fig)
    out.update(out_bio)
    out["other_figures"] = other
    out["notes"] = notes
    return out


def _consistency_notes(fig: dict, record: Optional[dict]) -> List[str]:
    """Places where the page disagrees with itself. Informational: no value is changed."""
    notes: List[str] = []
    landed = fig["sig_str_landed"]
    for label, keys in (("position", ("sig_str_standing", "sig_str_clinch", "sig_str_ground")),
                        ("target", ("sig_str_head", "sig_str_body", "sig_str_leg"))):
        values = [fig[k] for k in keys]
        if landed is not None and None not in values and sum(values) != landed:
            notes.append(f"strikes by {label} add up to {sum(values)} but sig_str_landed is {landed}")
    for pct_field, num_field, den_field in (("sig_str_accuracy_pct", "sig_str_landed", "sig_str_attempted"),
                                            ("takedown_accuracy_pct", "takedowns_landed", "takedowns_attempted")):
        pct, num, den = fig[pct_field], fig[num_field], fig[den_field]
        if None not in (pct, num, den) and den and abs(100.0 * num / den - pct) > 1.0:
            notes.append(f"{pct_field} is {pct} but {num_field}/{den_field} is {num}/{den}")
    methods = [fig["wins_ko"], fig["wins_dec"], fig["wins_sub"]]
    if record and None not in methods and sum(methods) != record["wins"]:
        notes.append(f"wins by method add up to {sum(methods)} but the record shows {record['wins']} wins")
    return notes


# -- slugs ------------------------------------------------------------------------------

_SUFFIXES = ("jr", "sr", "ii", "iii", "iv")
_PARTICLES = frozenset({"da", "das", "de", "del", "della", "di", "do", "dos", "du", "van", "von", "der",
                        "den", "la", "le", "el", "al", "bin", "ibn", "ben"})
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def slug_candidates(fighter: dict, *, limit: int = MAX_SLUG_CANDIDATES) -> List[str]:
    """UFC.com athlete slugs to try for one fighter, most likely first, no duplicates, at most `limit`.

    Order: ESPN's slug; the name as a slug (accents folded, punctuation dropped: "ismail-naurdiev",
    "jiri-prochazka", "sean-omalley"; initials joined: "tj-dillashaw"); the name without a
    Jr/Sr/II suffix; surnames of two or more parts cut down (particles dropped: "rafael-anjos";
    first or last part only); an apostrophe read as a hyphen ("sean-o-malley"); the name plus the
    nickname ("bruno-silva-blindado", how UFC.com tells two men of one name apart); and the plain
    name with "-0" and "-1", UFC.com's numbered duplicates (/athlete/bruno-silva-0 is the second
    Bruno Silva). Those last two are guesses: /athlete/ismail-naurdiev-0 is not a duplicate but
    serves another fighter's page, so a numbered slug proves nothing until the page is checked.
    Every entry matches [a-z0-9-]; nothing else can reach a URL. A wrong guess costs one request
    (UFC.com answers 200 to it), and `fetch_profile` accepts a page only after checking it
    against the fighter.
    """
    out: List[str] = []

    def add(slug: Optional[str]) -> None:
        if slug and _SLUG.match(slug) and slug not in out:
            out.append(slug)

    first, last = fighter.get("first_name"), fighter.get("last_name")
    raws = [fighter.get("name"), " ".join(p for p in (first, last) if p)]
    token_lists: List[List[str]] = []
    for raw in raws:
        tokens = names.tokens(raw)
        if tokens:
            joined = fighters.collapse_initials(" ".join(tokens)).split()
            if joined not in token_lists:
                token_lists.append(joined)
            if tokens != joined and tokens not in token_lists:
                token_lists.append(tokens)

    add(str(fighter.get("espn_slug") or "").strip().lower())
    for tokens in token_lists:
        add("-".join(tokens))
    for tokens in token_lists:
        has_suffix = len(tokens) > 2 and tokens[-1] in _SUFFIXES
        core = tokens[:-1] if has_suffix else tokens
        if has_suffix:
            add("-".join(core))
        if len(core) >= 3:
            head, rest = core[0], core[1:]
            kept = [t for t in rest if t not in _PARTICLES]
            if kept and kept != rest:
                add("-".join([head] + kept))
            if rest[0] not in _PARTICLES:
                add("-".join([head, rest[0]]))
            add("-".join([head, rest[-1]]))
    for raw in raws:
        if raw and ("'" in raw or "’" in raw):
            add("-".join(names.tokens(raw.replace("'", " ").replace("’", " "))))
    primary = "-".join(token_lists[0]) if token_lists else ""
    if primary:
        nick = names.tokens(fighter.get("nickname"))
        if len(nick) > 1 and nick[0] == "the":
            nick = nick[1:]
        if nick:
            add(f"{primary}-{'-'.join(nick)}")
        add(f"{primary}-0")
        add(f"{primary}-1")
    return out[:max(int(limit), 0)]


# -- identity and fetching --------------------------------------------------------------

def _name_matches(fighter: dict, page_name: str) -> bool:
    fid = str(fighter["fighter_id"])
    forms = fighters.name_index([fighter]).get(fid, [])
    people = {fid: forms + [fighters.collapse_initials(f) for f in forms]}
    query = fighters.collapse_initials(names.normalise(page_name))
    return names.match(query, people).best == fid


def _record_gap(a: dict, b: dict) -> int:
    return sum(abs(int(a.get(k) or 0) - int(b.get(k) or 0)) for k in ("wins", "losses", "draws"))


def _verdict(fighter: dict, profile: dict) -> Tuple[str, Optional[str]]:
    """(outcome, matched_on): "accepted" with how, or the reason the page is not this fighter."""
    page_name = profile.get("page_name")
    if not page_name:
        return "no_name", None
    if not _name_matches(fighter, page_name):
        return "name_mismatch", None
    ours, theirs = fighter.get("record"), profile.get("record")
    if isinstance(ours, dict) and isinstance(theirs, dict):
        if _record_gap(ours, theirs) > RECORD_TOLERANCE:
            return "record_mismatch", None
        return "accepted", "name+record"
    return "accepted", "name"


@dataclass
class ProfileLookup:
    """`record` is the profile to store (or None) and `tried` says what each slug did, in order:
    {"slug", "outcome"} with outcome "not_found", "no_name", "name_mismatch", "record_mismatch" or "accepted"."""

    record: Optional[dict] = None
    tried: List[dict] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lookup_profile(fetcher: PoliteFetcher, fighter: dict, *, max_age_s: Optional[float] = None,
                   candidates: Optional[List[str]] = None) -> ProfileLookup:
    """Try each slug in turn; return the first page that is this fighter, with the trail of what was tried.

    A 404 moves on to the next slug, and so does a 200 that is not this fighter: the search page
    UFC.com serves for a slug it lacks ("no_name"), another fighter's page ("name_mismatch") or a
    namesake with a different record ("record_mismatch"). None of those is ever returned. A browser
    check (SourceBlocked), any other failed request and the request cap propagate: nothing here
    catches them.
    """
    fid = str(fighter.get("fighter_id") or "").strip()
    if not fid:
        raise ValueError("fighter has no fighter_id")
    if not fighters.name_index([fighter]).get(fid):
        raise ValueError(f"fighter {fid} has no name to check a page against")
    result = ProfileLookup()
    for slug in (candidates if candidates is not None else slug_candidates(fighter)):
        url = espn_urls.ufccom_athlete(slug)
        try:
            html = fetcher.get_text(url, max_age_s=max_age_s)
        except NotFound:
            result.tried.append({"slug": slug, "outcome": "not_found"})
            continue
        profile = parse_profile(html)
        outcome, matched_on = _verdict(fighter, profile)
        result.tried.append({"slug": slug, "outcome": outcome})
        if outcome != "accepted":
            continue
        record = {"fighter_id": fid, "source_url": url,
                  "fetched_utc": fetcher.fetched_utc(url) or _now_iso(), "matched_on": matched_on}
        record.update(profile)
        record["ufc_slug"] = profile.get("ufc_slug") or slug
        result.record = record
        return result
    return result


def fetch_profile(fetcher: PoliteFetcher, fighter: dict, *, max_age_s: Optional[float] = None) -> Optional[dict]:
    """The `ufccom_profiles.jsonl` record for `fighter`, or None when no UFC.com page is verifiably theirs.

    `max_age_s` is passed to the fetcher: career figures change after every fight, so a refresh passes it.
    Use `lookup_profile` when the reason for a None matters.
    """
    return lookup_profile(fetcher, fighter, max_age_s=max_age_s).record
