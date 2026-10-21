"""Build config/gematria/team_facts.json: the public facts the Gematria Hound reads about each team.

    python scripts/build_gematria_facts.py                 # all of NFL, NBA, NHL and the college teams in our ESPN store
    python scripts/build_gematria_facts.py --sport nba     # one sport
    python scripts/build_gematria_facts.py --cache DIR     # keep raw fetches here (re-runs cost nothing)

WHY A SCRIPT AND NOT A HAND-TYPED TABLE. Every fact in the file carries the URL it came from, and a fact that
could not be read from a source is ABSENT, never guessed (the hound treats an absent fact as "no signal from this
fact", which is the honest outcome). A hand-typed table of 200 founding dates is exactly where a wrong date
would hide.

SOURCES (free, public)
  ESPN site API   team name, city, mascot, home venue state (NFL/NBA/NHL), and ESPN's core API for the current head
                  coach. The same ESPN endpoints the data service already reads (src/datasvc/espn).
  Wikipedia       the infobox ``founded`` / ``established`` line of the team's article (and, for a college team, of its
                  university's article, which also names the university's state). Read through the MediaWiki API
                  (the same text WebFetch would show), parsed by ``parse_infobox_date``.

A date keeps the precision the infobox gave it: ``"day"`` when it named a day, ``"year"`` when it named a year. The
hound only builds day- or week-spans from a ``"day"`` fact.

This is a build-time tool: the hound itself never fetches anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.hounds.gematria import facts as facts_mod          # noqa: E402  (the shared name key and state table)
from src.research import gematria                           # noqa: E402

UA = {"User-Agent": "LineHound-research/1.0 (paper-only sports analysis; contact via site)"}
ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports"
WIKI_API = "https://en.wikipedia.org/w/api.php"
LEAGUES = {"nfl": ("football", "nfl"), "nba": ("basketball", "nba"), "nhl": ("hockey", "nhl"),
           "ncaaf": ("football", "college-football")}
ESPN_DIRS = {"nfl": None, "nba": "nba", "nhl": "nhl", "ncaaf": "ncaaf"}
THROTTLE_S = 0.12
WIKI_THROTTLE_S = 0.7          # Wikipedia asked for a polite rate; a few hundred pages take a few minutes

# Names the odds feed spells differently from ESPN (the feed is what the hound sees at lock).
FEED_ALIASES = {
    "nba": {"Los Angeles Clippers": "LA Clippers"},
    "nhl": {"St Louis Blues": "St. Louis Blues", "Montr�al Canadiens": "Montréal Canadiens",
            "Montreal Canadiens": "Montréal Canadiens"},
    "ncaaf": {"Sam Houston State Bearkats": "Sam Houston Bearkats", "Appalachian State Mountaineers": "App State Mountaineers"},
    "nfl": {},
}


class Fetcher:
    def __init__(self, cache: Optional[Path]):
        self.cache = cache
        if cache:
            cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> Optional[dict]:
        key = None
        if self.cache:
            key = self.cache / (re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:] + ".json")
            if key.exists():
                return json.loads(key.read_text(encoding="utf-8"))
        throttle = WIKI_THROTTLE_S if "wikipedia.org" in url else THROTTLE_S
        data = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 5:          # polite: back off and try again, never hammer
                    time.sleep(min(60.0, float(exc.headers.get("Retry-After") or 5 * (attempt + 1))))
                    continue
                print(f"  fetch failed {url}: {exc}", file=sys.stderr)
                return None
            except Exception as exc:  # noqa: BLE001 -- a missing source means a missing fact, not a crash
                print(f"  fetch failed {url}: {exc}", file=sys.stderr)
                return None
        time.sleep(throttle)
        if key is not None and data is not None:
            key.write_text(json.dumps(data), encoding="utf-8")
        return data


# ---------------------------------------------------------------------------
# wikipedia infobox
# ---------------------------------------------------------------------------

PREFETCH: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
BATCH = 20                          # titles per MediaWiki request; a few hundred pages are then a few dozen requests


def _page_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))


def prefetch_wikitext(fetch: Fetcher, titles) -> None:
    """Fetch many articles in a few requests (Wikipedia rate-limits one-page-per-request crawls hard) into ``PREFETCH``.
    Redirects and title normalisation are followed; a requested title maps to its final article's text and URL."""
    todo = sorted({t for t in titles if t and t not in PREFETCH})
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        q = urllib.parse.urlencode({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                                    "titles": "|".join(chunk), "redirects": 1, "format": "json", "formatversion": 2})
        data = fetch.get(f"{WIKI_API}?{q}")
        if not data:
            continue
        query = data.get("query") or {}
        hop = {}
        for m in (query.get("normalized") or []) + (query.get("redirects") or []):
            hop[m["from"]] = m["to"]
        pages = {p.get("title"): p for p in query.get("pages") or [] if isinstance(p, dict)}
        for t in chunk:
            final = t
            for _ in range(4):
                final = hop.get(final, final)
            page = pages.get(final)
            try:
                PREFETCH[t] = (page["revisions"][0]["slots"]["main"]["content"], _page_url(page["title"]))
            except (TypeError, KeyError, IndexError):
                PREFETCH[t] = (None, None)


def wikitext(fetch: Fetcher, title: str) -> Tuple[Optional[str], Optional[str]]:
    """(wikitext, article URL) for a page title, following redirects. (None, None) when there is no page."""
    if title not in PREFETCH:
        prefetch_wikitext(fetch, [title])
    return PREFETCH.get(title, (None, None))


_MONTHS = {m: i + 1 for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"))}


def infobox_field(text: str, *names: str) -> Optional[str]:
    """The raw value of the first infobox parameter in ``names`` (case-insensitive), up to the next parameter."""
    for name in names:
        m = re.search(r"^\s*\|\s*" + re.escape(name) + r"\s*=\s*(.*?)(?=^\s*\||^\}\}|\Z)", text,
                      re.I | re.S | re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def _clean(value: str) -> str:
    value = re.sub(r"<ref[^>]*?/>|<ref.*?</ref>|<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", value)       # [[a|b]] -> b
    value = re.sub(r"\{\{\s*(?:nowrap|small)\s*\|([^}]*)\}\}", r"\1", value, flags=re.I)
    return value.strip()


def parse_infobox_date(raw: Optional[str]) -> Optional[dict]:
    """{"date": "YYYY-MM-DD" | "YYYY", "precision": "day" | "year"} from an infobox ``founded`` value, or None.

    Handles ``{{start date|1946|6|6}}`` (and its ``and age`` kin), "June 6, 1946", "6 June 1946" and a bare year. When
    a value holds SEVERAL dates (a team refounded or moved) the FIRST is taken, which is the original founding."""
    if not raw:
        return None
    m = re.search(r"\{\{\s*(?:start|birth|death)[ _]date(?:[ _]and[ _]age)?\s*\|([^}]*)\}\}", raw, re.I)
    if m:
        parts = [p.strip() for p in m.group(1).split("|") if "=" not in p]
        nums = [p for p in parts if p.isdigit()]
        if len(nums) >= 3:
            y, mo, d = int(nums[0]), int(nums[1]), int(nums[2])
            return {"date": f"{y:04d}-{mo:02d}-{d:02d}", "precision": "day"}
        if len(nums) == 1 and 1500 < int(nums[0]) < 2100:
            return {"date": f"{int(nums[0]):04d}", "precision": "year"}
    text = _clean(raw)
    m = re.search(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", text, re.I)
    if m:
        return {"date": f"{int(m.group(3)):04d}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}", "precision": "day"}
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", text, re.I)
    if m:
        return {"date": f"{int(m.group(3)):04d}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}", "precision": "day"}
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", text)
    if m:
        return {"date": m.group(1), "precision": "year"}
    return None


def _state_in_text(text: str) -> Optional[str]:
    """The one U.S. state named in a location line ("Statesboro, Georgia, U.S."), or None when none or several are named."""
    found = {name for name in facts_mod.STATE_ADMITTED
             if re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", text)}
    if "Washington" in found and "D.C" in text:
        found.discard("Washington")
    for inner in ("Virginia", "Dakota", "Carolina", "York", "Mexico", "Hampshire", "Jersey"):
        found.discard(inner) if inner in found else None
    if "West Virginia" in found:
        found.discard("Virginia")
    return found.pop() if len(found) == 1 else None


def first_link(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    m = re.search(r"\[\[([^\]|#]+)", raw)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# per-sport assembly
# ---------------------------------------------------------------------------

def fact(value, source: str, **extra) -> dict:
    out = {"value": value, "source": source}
    out.update(extra)
    return out


def dated(parsed: dict, source: str) -> dict:
    return {"date": parsed["date"], "precision": parsed["precision"], "source": source}


def espn_teams(sport: str) -> Dict[str, dict]:
    """{team_id: {display_name, location, name}} for the sport from the local ESPN store (no network)."""
    out: Dict[str, dict] = {}
    league_dir = REPO / "data/datasvc/espn" / ESPN_DIRS[sport]
    for line in (league_dir / "teams.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("is_active", True):
            out[str(r["team_id"])] = {"display_name": r["display_name"], "location": r.get("location"),
                                      "name": r.get("name"), "abbr": r.get("abbreviation")}
    if sport == "ncaaf":
        played = set()
        for f in sorted(league_dir.glob("games_*.jsonl")):
            for line in f.open(encoding="utf-8"):
                g = json.loads(line)
                played.add(str(g["home_id"]))
                played.add(str(g["away_id"]))
        out = {k: v for k, v in out.items() if k in played}
    return out


def nfl_teams(fetch: Fetcher) -> Dict[str, dict]:
    data = fetch.get(f"{ESPN_SITE}/football/nfl/teams?limit=50") or {}
    out = {}
    try:
        for t in data["sports"][0]["leagues"][0]["teams"]:
            t = t["team"]
            out[str(t["id"])] = {"display_name": t["displayName"], "location": t.get("location"), "name": t.get("name"),
                                 "abbr": t.get("abbreviation")}
    except (KeyError, IndexError):
        pass
    return out


def head_coach(fetch: Fetcher, sport: str, team_id: str, season: int) -> Optional[dict]:
    kind, league = LEAGUES[sport]
    list_url = f"{ESPN_CORE}/{kind}/leagues/{league}/seasons/{season}/teams/{team_id}/coaches"
    listing = fetch.get(list_url)
    try:
        ref = listing["items"][0]["$ref"].replace("http://", "https://")
    except (TypeError, KeyError, IndexError):
        return None
    coach = fetch.get(ref)
    if not coach or not coach.get("lastName"):
        return None
    return fact(f"{coach.get('firstName', '')} {coach['lastName']}".strip(), list_url,
                season=season, experience_years=coach.get("experience"))


def build_team(fetch: Fetcher, sport: str, team_id: str, info: dict, season: int, observed: str) -> dict:
    kind, league = LEAGUES[sport]
    team_url = f"{ESPN_SITE}/{kind}/{league}/teams/{team_id}"
    entry: dict = {"sport": sport, "espn_id": team_id, "name": info["display_name"],
                   "aliases": sorted(a for a, canon in FEED_ALIASES.get(sport, {}).items() if canon == info["display_name"]),
                   "observed_utc": observed}
    if info.get("location"):
        entry["city"] = fact(info["location"], team_url)
    if info.get("name"):
        entry["mascot"] = fact(info["name"], team_url)
    if info.get("abbr") and sport != "ncaaf":          # a college abbreviation is ESPN's own shorthand, not a name anyone uses
        entry["abbr"] = fact(info["abbr"], team_url)
    wiki, wurl = wikitext(fetch, info["display_name"])
    if sport in ("nfl", "nba", "nhl"):
        tdata = (fetch.get(team_url) or {}).get("team") or {}
        st = (((tdata.get("franchise") or {}).get("venue") or {}).get("address") or {}).get("state")
        name = facts_mod.state_name(st)
        if name:
            entry["state"] = fact(name, team_url, admitted=facts_mod.STATE_ADMITTED[name][1],
                                  admitted_order=facts_mod.STATE_ADMITTED[name][0])
        if wiki:
            parsed = parse_infobox_date(infobox_field(wiki, "founded", "established"))
            if parsed:
                entry["founded"] = dated(parsed, wurl)
    elif wiki:
        uni_title = first_link(infobox_field(wiki, "university", "school"))
        if uni_title:
            uwiki, uurl = wikitext(fetch, uni_title)
            if uwiki:
                entry["university"] = fact(uni_title, uurl)
                parsed = parse_infobox_date(infobox_field(uwiki, "established", "founded", "established_date"))
                if parsed:
                    entry["university_founded"] = dated(parsed, uurl)
                sname = facts_mod.state_name(_clean(infobox_field(uwiki, "state", "province") or ""))
                if not sname:
                    sname = _state_in_text(_clean(" ".join(infobox_field(uwiki, f) or "" for f in ("location", "city", "campus", "address"))))
                if sname:
                    entry["state"] = fact(sname, uurl, admitted=facts_mod.STATE_ADMITTED[sname][1],
                                          admitted_order=facts_mod.STATE_ADMITTED[sname][0])
    coach = head_coach(fetch, sport, team_id, season)
    if coach:
        entry["head_coach"] = coach
    return entry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sport", choices=sorted(LEAGUES), action="append")
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=REPO / "config/gematria/team_facts.json")
    ap.add_argument("--limit", type=int, default=0, help="first N teams per sport (smoke test)")
    args = ap.parse_args(argv)
    fetch = Fetcher(args.cache)
    observed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = {}
    if args.out.exists():
        existing = json.loads(args.out.read_text(encoding="utf-8")).get("teams", {})
    teams = dict(existing)
    rosters = {}
    for sport in args.sport or sorted(LEAGUES):
        roster = nfl_teams(fetch) if sport == "nfl" else espn_teams(sport)
        items = sorted(roster.items(), key=lambda kv: kv[1]["display_name"])
        rosters[sport] = items[:args.limit] if args.limit else items
    prefetch_wikitext(fetch, [info["display_name"] for items in rosters.values() for _tid, info in items])
    uni = set()
    for _tid, info in rosters.get("ncaaf", []):
        text, _u = PREFETCH.get(info["display_name"], (None, None))
        t = first_link(infobox_field(text, "university", "school")) if text else None
        if t:
            uni.add(t)
    prefetch_wikitext(fetch, uni)
    for sport in args.sport or sorted(LEAGUES):
        # ESPN's season year for a winter sport is the year it ends (NBA 2026-27 is 2027); the football seasons are the year they start.
        season = {"nba": 2027, "nhl": 2027}.get(sport, 2026)
        print(f"{sport}: {len(rosters[sport])} teams", flush=True)
        for tid, info in rosters[sport]:
            entry = build_team(fetch, sport, tid, info, season, observed)
            teams[facts_mod.team_key(sport, entry["name"])] = entry
    payload = {"version": 1, "built_utc": observed,
               "note": ("Every fact carries its source URL. A fact that could not be read is absent, never guessed. "
                        "Built by scripts/build_gematria_facts.py; the hound never fetches."),
               "teams": dict(sorted(teams.items()))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(teams)} teams)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
