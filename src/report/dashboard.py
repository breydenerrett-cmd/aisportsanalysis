"""Static HTML briefing. One file, no server, no network, no dependencies.

WHY A GENERATED STATIC FILE
---------------------------
The briefing has to be openable on a phone, sendable to someone else, and
readable a year from now. A served dashboard needs the server to still be
running; a static file needs nothing. It also means the artifact is a snapshot:
the page for a given date shows what was known on that date and cannot silently
change when the data behind it does.

Everything is inlined and the page works from a file:// URL with the network
switched off.

IT IS ALSO RENDERED SERVER-SIDE, WITH NO JAVASCRIPT AT ALL
An earlier version built the whole page in JS from an embedded JSON blob. That
works in a normal browser tab and produces a COMPLETELY BLANK PAGE anywhere
inline scripts are blocked -- a sandboxed preview pane, a strict CSP, a mail
client, a viewer with scripting off. It failed exactly that way the first time
it was opened somewhere other than here.

A briefing that is blank in half the places it gets opened is not a briefing, so
the HTML is now the content. Expand and collapse use <details>/<summary>, which
is native browser behaviour and needs no script. There is no JavaScript in the
output.

WHY EVERY CLAIM CARRIES AN EVIDENCE LABEL
-----------------------------------------
This project has one recurring failure mode: a number that is technically true
being read as a validated result. The reader cannot be expected to remember which
parts are proven, so the page never lets them guess -- every claim is stamped
with its status, and "unproven" is the default that has to be argued out of.

A page that looks confident about an unvalidated threshold is worse than no page.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from src.detect import base as detect

EVIDENCE_LABELS = {
    detect.PROVEN: ("Proven", "Held up on data it was not built from"),
    detect.FORWARD_TESTING: ("Forward testing", "Logged before the games; still accumulating"),
    detect.PROVISIONAL: ("Provisional", "One-shot backtest; weaker than forward proof"),
    detect.TUNING_EVIDENCE: ("Tuning evidence", "Thresholds were fitted on this; optimistic"),
    detect.HISTORICAL_CANDIDATE: ("Candidate", "Looks real in discovery data; untested"),
    detect.UNPROVEN: ("Unproven", "A written-down guess. Never tested."),
    detect.TESTED_NULL: ("Tested — no edge",
                         "Measured against outcomes and it did not predict them"),
    detect.BLOCKED: ("Blocked", "Cannot be computed with the data we have"),
}


def render(slate, out_path, generated_at=None) -> str:
    """Write the briefing for one slate. Returns the path written."""
    stamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = _payload(slate, stamp)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_document(payload), encoding="utf-8")
    return str(target)


def _payload(slate, stamp) -> dict:
    games = []
    for entry in slate.get("games", []):
        dossier = entry["dossier"]
        findings = entry.get("findings", [])
        games.append({
            "away": dossier.game.get("away_team"),
            "home": dossier.game.get("home_team"),
            "start": dossier.game.get("start_time_utc"),
            "venue": dossier.game.get("venue"),
            "verdict": entry.get("verdict", "no_play"),
            "side": entry.get("side"),
            "market": entry.get("market"),
            "summary": entry.get("summary"),
            "findings": [_finding(f) for f in findings],
            "sections": _sections(dossier),
            "gaps": dossier.gaps,
        })
    return {
        "date": slate.get("date"),
        "generated_at": stamp.isoformat(),
        "games": games,
        "counts": {
            "games": len(games),
            "flagged": sum(1 for g in games if g["verdict"] == "flagged"),
            "candidates": sum(1 for g in games if g["verdict"] == "candidate"),
            "no_market": sum(1 for g in games
                             if g["verdict"] == "market_unavailable"),
        },
        "notes": slate.get("notes", []),
    }


def _finding(finding) -> dict:
    label, meaning = EVIDENCE_LABELS.get(finding.evidence,
                                         (finding.evidence, ""))
    return {
        "detector": finding.detector,
        "kind": finding.kind,
        "claim": finding.claim,
        "value": finding.value,
        "baseline": finding.baseline,
        "sample": finding.sample,
        "surprise": finding.surprise,
        "side": finding.side,
        "market_relevance": finding.market_relevance,
        "evidence": finding.evidence,
        "evidence_label": label,
        "evidence_meaning": meaning,
        "detail": _plain(finding.detail),
    }


def _sections(dossier) -> dict:
    return {name: _plain(data) for name, data in dossier.sections.items()}


def _plain(value):
    """Make a value JSON-safe without ever inventing one.

    An unserialisable object becomes its repr rather than being dropped. A
    dropped field looks like missing data and would be read as "no value", which
    is a different and false statement.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return repr(value)


# ---------------------------------------------------------------------------
# Rendering. Server-side, no JavaScript in the output.
# ---------------------------------------------------------------------------

def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value, digits=2) -> str:
    if value is None or value == "":
        return "--"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return _esc(value)


def _pct(value) -> str:
    return "--" if value is None else f"{value * 100:.1f}%"


def _american(value) -> str:
    if value is None:
        return "--"
    try:
        value = int(value)
    except (TypeError, ValueError):
        return _esc(value)
    return f"+{value}" if value > 0 else str(value)


def _local_time(iso) -> str:
    """First pitch, in the venue's own clock is not available here, so UTC is
    labelled as UTC rather than shown bare and misread as local."""
    if not iso:
        return ""
    try:
        stamp = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return stamp.astimezone(timezone.utc).strftime("%H:%M UTC")


VERDICT_LABELS = {
    "flagged": "flagged",
    "candidate": "candidate",
    "no_play": "no play",
    "market_unavailable": "no market",
}


def _table(rows, headers=None) -> str:
    if not rows:
        return ""
    numeric = ' class="n"'
    out = ['<div class="tw"><table>']
    if headers:
        cells = "".join("<th" + (numeric if i else "") + ">" + _esc(h) + "</th>"
                        for i, h in enumerate(headers))
        out.append(f"<thead><tr>{cells}</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        cells = "".join("<td" + (numeric if i else "") + ">" + _esc(c) + "</td>"
                        for i, c in enumerate(row))
        out.append(f"<tr>{cells}</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def _chip(finding) -> str:
    return (f'<span class="chip {_esc(finding["evidence"])}" '
            f'title="{_esc(finding["evidence_meaning"])}">'
            f'{_esc(finding["evidence_label"])}</span>')


def _spark(finding) -> str:
    value = finding.get("surprise")
    return "&mdash;" if value is None else f"{value:.1f}"


def _finding_row(finding) -> str:
    support = []
    if finding.get("value") is not None:
        support.append(f'<span class="mono">value {_num(finding["value"])}</span>')
    if finding.get("baseline") is not None:
        support.append(f'<span class="mono">normal {_num(finding["baseline"])}</span>')
    if finding.get("sample") is not None:
        support.append(f'<span class="mono">sample {_esc(finding["sample"])}</span>')
    support.append(_chip(finding))
    relevance = (f'<div class="support">{_esc(finding["market_relevance"])}</div>'
                 if finding.get("market_relevance") else "")
    return (
        f'<div class="finding {_esc(finding["kind"])}">'
        f'<div class="spark">{_spark(finding)}</div>'
        f'<div><div class="claim">{_esc(finding["claim"])}</div>'
        f'<div class="support">{"".join(support)}</div>{relevance}</div></div>')


def _lead(games) -> str:
    """The slate summary: each detector's single strongest finding."""
    picks, seen = [], set()
    ordered = []
    for index, game in enumerate(games):
        for finding in game["findings"]:
            if finding["kind"] != "context":
                ordered.append((index, game, finding))
    ordered.sort(key=lambda item: (
        0 if item[2]["kind"] == "signal" else 1, -(item[2]["surprise"] or 0)))
    for index, game, finding in ordered:
        if finding["detector"] in seen:
            continue
        seen.add(finding["detector"])
        picks.append((index, game, finding))

    if not picks:
        if not games:
            return ""
        return (
            '<section class="lead"><h2>Nothing unusual on this slate</h2>'
            '<p class="claim">No detector found anything out of the ordinary. '
            'That is the normal case, not a failure &mdash; most days of '
            'major-league baseball are two roughly major-league teams playing a '
            'close game.</p></section>')

    rows = []
    for index, game, finding in picks[:6]:
        rows.append(
            f'<a class="leaditem" href="#game-{index}">'
            f'<div class="spark {_esc(finding["kind"])}">{_spark(finding)}</div>'
            f'<div><div class="leadmatch">{_esc(game["away"])} @ '
            f'{_esc(game["home"])}</div>'
            f'<div class="claim">{_esc(finding["claim"])}</div></div></a>')
    return (
        '<section class="lead"><h2>Most unusual on this slate</h2>'
        '<p class="leadnote">Ranked by how far each number sits from normal '
        '&mdash; that is rarity, not importance. No effect size has been '
        'measured yet, so a rare fact and an important one are not yet '
        'distinguishable here. One line per detector.</p>'
        f'<div class="leadlist">{"".join(rows)}</div></section>')


def _market_section(game) -> str:
    section = game["sections"].get("market")
    if not section:
        return _gap_block("Market", game["gaps"].get("market", "no prices"))
    sides, totals = [], []
    for key in sorted(section.get("markets") or {}):
        market = section["markets"][key]
        if market.get("total") is not None:
            totals.append([key, _num(market["total"], 1),
                           _american(market.get("over_price")),
                           _american(market.get("under_price")),
                           _pct(market.get("over_fair")),
                           _pct(market.get("under_fair"))])
        elif market.get("away_price") is not None:
            label = key + (f' ({_num(market["home_line"], 1)})'
                           if market.get("home_line") is not None else "")
            sides.append([label, _american(market["away_price"]),
                          _american(market.get("home_price")),
                          _pct(market.get("away_fair")),
                          _pct(market.get("home_fair")),
                          "--" if market.get("hold_pct") is None
                          else f'{market["hold_pct"]:.2f}%'])
    parts = ["<h3>Market</h3>"]
    if sides:
        parts.append(_table(sides, ["market", "away", "home", "away fair",
                                    "home fair", "hold"]))
    if totals:
        parts.append(_table(totals, ["total", "line", "over", "under",
                                     "over fair", "under fair"]))
    if not sides and not totals:
        parts.append('<p class="gap">no market priced this game</p>')
    shift = section.get("implied_bullpen_shift")
    if shift is not None:
        who = game["home"] if shift > 0 else game["away"]
        parts.append(
            f'<p class="support">Implied bullpen read: the market gives '
            f'{_esc(who)} {abs(shift) * 100:.1f} points of win probability from '
            f'innings 6&ndash;9 &mdash; the gap between the full-game and '
            f'first-five prices is its bullpen opinion.</p>')
    return "".join(parts)


def _gap_block(title, reason) -> str:
    reason = _esc(reason or "not available")
    return f'<h3>{_esc(title)}</h3><p class="gap">{reason}</p>' 


def _starters_section(game) -> str:
    starters = game["sections"].get("starters")
    if not starters:
        return _gap_block("Starting pitchers", game["gaps"].get("starters"))
    fields = [("FIP", "sp_fip", 2), ("ERA", "sp_era", 2), ("WHIP", "sp_whip", 2),
              ("K/9", "sp_k9", 2), ("BB/9", "sp_bb9", 2),
              ("K-BB%", "sp_k_bb_pct", 3), ("IP", "sp_innings", 1),
              ("IP/start", "sp_ip_per_start", 2), ("rest", "sp_days_rest", 0)]
    rows = [[label, _num(starters.get("away_" + key), digits),
             _num(starters.get("home_" + key), digits)]
            for label, key, digits in fields]
    parts = ["<h3>Starting pitchers</h3>",
             _table(rows, ["", game["away"], game["home"]])]

    splits = game["sections"].get("splits") or {}
    split_rows = []
    for side, team in (("away", game["away"]), ("home", game["home"])):
        record = ((splits.get(side) or {}).get("record") or {}).get("splits") or {}
        for key in ("Home Games", "Away Games", "vs Left", "vs Right"):
            row = record.get(key)
            if row:
                split_rows.append([f"{team} — {key}", _num(row.get("ops"), 3),
                                   row.get("batters_faced") or "--",
                                   row.get("innings") or "--"])
    if split_rows:
        parts.append("<h3>Starter splits (OPS allowed)</h3>")
        parts.append(_table(split_rows, ["split", "OPS", "BF", "IP"]))
    if starters.get("either_sp_thin"):
        parts.append('<p class="gap">One starter is under the innings threshold '
                     '&mdash; his rates are small-sample noise and are suppressed '
                     'rather than shown.</p>')
    return "".join(parts)


def _lineups_section(game) -> str:
    lineups = game["sections"].get("lineups")
    if not lineups:
        return _gap_block("Lineups and platoon", game["gaps"].get("lineups"))
    splits = game["sections"].get("splits") or {}
    parts = ["<h3>Lineups and platoon</h3>"]
    for side, team, opposing in (("away", game["away"], "home"),
                                 ("home", game["home"], "away")):
        entry = lineups.get(side) or {}
        counts = entry.get("handedness") or {}
        advantage = entry.get("platoon_advantage") or {}
        throws = entry.get("faces_starter_throwing")
        parts.append(f'<h3>{_esc(team)} lineup vs '
                     f'{_esc(throws + "HP" if throws else "starter")}</h3>')
        rows = [[f'{b.get("order")}. {b.get("name")}', b.get("position") or ""]
                for b in entry.get("batters") or []]
        parts.append(_table(rows))
        line = (f'{counts.get("L", 0)}L / {counts.get("R", 0)}R / '
                f'{counts.get("S", 0)}S')
        if advantage.get("share") is not None:
            line += (f' · {advantage["advantaged"]} of {advantage["known"]} with '
                     f'the platoon advantage ({_pct(advantage["share"])})')
        elif advantage.get("reason"):
            line += f' · {advantage["reason"]}'
        parts.append(f'<p class="support">{_esc(line)}</p>')
        split = ((splits.get(opposing) or {}).get("platoon")) or {}
        if split.get("usable"):
            parts.append(
                f'<p class="support">That starter allows '
                f'{_num(split["vs_left_ops"], 3)} OPS to lefties and '
                f'{_num(split["vs_right_ops"], 3)} to righties '
                f'({split["vs_left_faced"]} and {split["vs_right_faced"]} '
                f'batters faced).</p>')
        elif split.get("reason"):
            parts.append(f'<p class="gap">{_esc(split["reason"])}</p>')
    return "".join(parts)


def _matchup_section(game) -> str:
    history = game["sections"].get("matchup_history")
    if not history:
        return _gap_block("This lineup vs tonight's starter",
                          game["gaps"].get("matchup_history"))
    parts = ["<h3>This lineup vs tonight&rsquo;s starter</h3>"]
    for side, team in (("away", game["away"]), ("home", game["home"])):
        entry = history.get(side)
        if not entry:
            continue
        parts.append(f"<h3>{_esc(team)}</h3>")
        rows = []
        for batter in entry.get("batters") or []:
            at_bats = batter.get("at_bats") or 0
            rows.append([
                f'{batter.get("name")}'
                + (f' ({batter["bats"]})' if batter.get("bats") else ""),
                at_bats, batter.get("hits"), batter.get("home_runs"),
                batter.get("strikeouts"),
                f'{batter["hits"] / at_bats:.3f}' if at_bats else "--"])
        parts.append(_table(rows, ["batter", "AB", "H", "HR", "K", "AVG"]))
        if entry.get("usable"):
            parts.append(
                f'<p class="support">Combined {entry["total_hits"]}-for-'
                f'{entry["total_at_bats"]} ({_num(entry["aggregate_avg"], 3)}). '
                f'Large enough to be worth something.</p>')
        else:
            parts.append(f'<p class="gap">{_esc(entry.get("reason") or "sample too small")}</p>')
    return "".join(parts)


def _teams_section(game) -> str:
    teams = game["sections"].get("teams")
    if not teams:
        return _gap_block("Teams", game["gaps"].get("teams"))
    fields = [("Record", "wins", 0), ("Win %", "win_pct", 3),
              ("Runs/gm", "runs_scored_pg", 2), ("Allowed/gm", "runs_allowed_pg", 2),
              ("Run diff/gm", "run_diff_pg", 2), ("Last 10 wins", "last10_wins", 0),
              ("Rest days", "rest_days", 0)]
    rows = [[label, _num(teams.get("away_" + key), digits),
             _num(teams.get("home_" + key), digits)]
            for label, key, digits in fields]
    return "<h3>Teams</h3>" + _table(rows, ["", game["away"], game["home"]])


def _environment_section(game) -> str:
    park = game["sections"].get("park") or {}
    weather = game["sections"].get("weather") or {}
    rows = []
    if park:
        rows += [["Park", park.get("name")], ["Roof", park.get("roof")],
                 ["Altitude (m)", _num(park.get("altitude_m"), 0)]]
    if weather:
        rows += [["Temp (F)", _num(weather.get("temp_f"), 0)],
                 ["Wind (mph)", _num(weather.get("wind_mph"), 0)],
                 ["Humidity", _num(weather.get("humidity_pct"), 0)]]
    if not rows:
        return _gap_block("Environment",
                          game["gaps"].get("park") or game["gaps"].get("weather"))
    parts = ["<h3>Environment</h3>", _table(rows)]
    if park and park.get("orientation_deg") is None:
        parts.append('<p class="gap">Wind direction is not interpreted: park '
                     'orientation is unknown, and a wrong bearing would invert a '
                     'real effect.</p>')
    return "".join(parts)


def _gaps_section(game) -> str:
    if not game["gaps"]:
        return ""
    rows = "".join(f'<p class="gap">{_esc(name)}: {_esc(reason)}</p>'
                   for name, reason in sorted(game["gaps"].items()))
    return f"<h3>Missing data</h3>{rows}"


def _game_card(index, game) -> str:
    verdict = game["verdict"]
    prices = []
    market = (game["sections"].get("market") or {}).get("markets") or {}
    if market.get("h2h"):
        prices.append(f'{_american(market["h2h"].get("away_price"))} / '
                      f'{_american(market["h2h"].get("home_price"))}')
    if market.get("h2h_1st_5_innings"):
        f5 = market["h2h_1st_5_innings"]
        prices.append(f'F5 {_american(f5.get("away_price"))} / '
                      f'{_american(f5.get("home_price"))}')
    price_html = "".join(f'<div class="price mono">{_esc(p)}</div>' for p in prices)

    meta = " · ".join(x for x in (_local_time(game.get("start")),
                                  game.get("venue")) if x)
    findings = "".join(_finding_row(f) for f in game["findings"])
    body = (
        ('<h3>Why this game is interesting</h3>'
         f'<div class="findings">{findings}</div>' if findings else
         '<h3>Why this game is interesting</h3>'
         '<p class="gap">No detector had anything to say about this game.</p>')
        + _market_section(game) + _starters_section(game)
        + _lineups_section(game) + _matchup_section(game)
        + _teams_section(game) + _environment_section(game)
        + _gaps_section(game))

    # <details> is native expand/collapse. No script, so it works in a sandboxed
    # preview, with a strict CSP, or with scripting switched off entirely.
    return (
        f'<details class="game {_esc(verdict)}" id="game-{index}"'
        f'{" open" if game.get("open") else ""}>'
        f'<summary class="gamehead">'
        f'<div><div class="match">{_esc(game["away"])} @ {_esc(game["home"])}</div>'
        f'<div class="meta">{_esc(meta)}</div>'
        f'<div class="meta">{_esc(game.get("summary") or "")}</div></div>'
        f'<div class="headright">'
        f'<div class="verdict {_esc(verdict)}">'
        f'{_esc(VERDICT_LABELS.get(verdict, verdict))}</div>{price_html}</div>'
        f'</summary><div class="body">{body}</div></details>')


def _document(payload) -> str:
    games = payload["games"]

    # Open the most interesting game. On a slate of fifteen no-plays an
    # all-collapsed page reads as though the tool found nothing at all.
    best_index, best_score = None, -1
    for index, game in enumerate(games):
        score = max([f["surprise"] or 0 for f in game["findings"]
                     if f["kind"] == "signal"] or [-1])
        if game["verdict"] != "no_play":
            score += 100
        if score > best_score:
            best_score, best_index = score, index
    if best_index is not None:
        games[best_index]["open"] = True

    counts = payload["counts"]
    tiles = "".join(
        f'<div class="count"><b>{counts.get(key, 0)}</b><span>{label}</span></div>'
        for key, label in (("games", "games"), ("flagged", "flagged"),
                           ("candidates", "candidates"), ("no_market", "no market")))

    legend, seen = [], set()
    for game in games:
        for finding in game["findings"]:
            if finding["evidence"] not in seen:
                seen.add(finding["evidence"])
                legend.append(_chip(finding))

    cards = "".join(_game_card(i, g) for i, g in enumerate(games)) or (
        '<p class="empty">No games scheduled for this date.</p>')
    notes = "".join(f"<div>{_esc(n)}</div>" for n in payload.get("notes") or [])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slate briefing {_esc(payload.get("date"))}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Slate briefing &mdash; {_esc(payload.get("date"))}</h1>
<div class="sub mono">generated {_esc(payload["generated_at"])} &middot; times in UTC</div>
<div class="counts">{tiles}</div>
<div class="legend">{"".join(legend)}</div>
</header>
{_lead(games)}
{cards}
<footer>{notes}<div>Paper only. No bet is placed by any code in this project.
Every threshold behind these verdicts is an unvalidated guess until the evidence
label says otherwise.</div></footer>
</div>
</body>
</html>
"""


_CSS = """
:root {
  --paper:#EBEEEA; --surface:#F7F9F5; --sunk:#E0E5DC; --ink:#151A16;
  --muted:#525E52; --faint:#84907F; --rule:#CBD2C6;
  --accent:#2B5F44; --clay:#A0522A; --warn:#8A6D1F;
}
@media (prefers-color-scheme: dark) {
  :root {
    /* On a dark ground a recessed panel has to go LIGHTER than the page, not
       darker -- inverting the light palette literally made the slate summary
       almost invisible against the body. */
    --paper:#0C100D; --surface:#141A15; --sunk:#1A211B; --ink:#DCE4DA;
    --muted:#8C9789; --faint:#67725F; --rule:#232B24;
    --accent:#79C298; --clay:#DE9463; --warn:#D6B45C;
  }
}
* { box-sizing:border-box; }
body {
  margin:0; padding:0 18px 80px; background:var(--paper); color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:1080px; margin:0 auto; }
header { padding:40px 0 22px; border-bottom:2px solid var(--ink); margin-bottom:26px; }
h1 { margin:0 0 6px; font-size:30px; letter-spacing:-.02em; }
.sub { color:var(--muted); font-size:14px; }
.mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.counts { display:flex; gap:22px; margin-top:16px; flex-wrap:wrap; }
.count b { display:block; font-size:26px; line-height:1.1; }
.count span { font-size:11px; letter-spacing:.09em; text-transform:uppercase; color:var(--faint); }

.legend { margin:18px 0 0; display:flex; gap:8px; flex-wrap:wrap; }
.chip {
  font-size:10px; letter-spacing:.08em; text-transform:uppercase; font-weight:700;
  padding:3px 8px; border-radius:2px; border:1px solid currentColor; white-space:nowrap;
}
.chip.proven{color:var(--accent)} .chip.forward_testing{color:var(--accent)}
.chip.provisional{color:var(--warn)} .chip.tuning_evidence{color:var(--warn)}
.chip.historical_candidate{color:var(--muted)} .chip.unproven{color:var(--clay)}
.chip.blocked{color:var(--faint)}

.lead { margin:0 0 26px; padding:20px 22px; background:var(--sunk);
        border:1px solid var(--rule); border-radius:5px; }
.lead h2 { margin:0 0 14px; font-size:13px; letter-spacing:.1em;
           text-transform:uppercase; color:var(--faint); font-weight:700; }
.leadnote { font-size:12.5px; color:var(--muted); margin:-6px 0 14px;
            max-width:70ch; line-height:1.45; }
.leadlist { display:flex; flex-direction:column; gap:11px; }
.leaditem { display:grid; grid-template-columns:52px 1fr; gap:14px;
            align-items:baseline; text-decoration:none; color:inherit; }
.leaditem:hover .claim { text-decoration:underline; }
.leaditem:focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
.leadmatch { font-size:11px; letter-spacing:.08em; text-transform:uppercase;
             color:var(--faint); font-weight:700; margin-bottom:2px; }

.game {
  border:1px solid var(--rule); border-radius:5px; background:var(--surface);
  margin-bottom:12px; overflow:hidden;
}
.game.flagged { border-left:5px solid var(--accent); }
.game.candidate { border-left:5px solid var(--warn); }
.game.no_play { border-left:5px solid var(--rule); }
.game.market_unavailable { border-left:5px dashed var(--clay); }
.gamehead {
  display:grid; grid-template-columns:1fr auto; gap:14px; align-items:start;
  padding:16px 18px; cursor:pointer; list-style:none;
}
.gamehead::-webkit-details-marker { display:none; }
.gamehead:hover { background:var(--sunk); }
.gamehead:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.headright { text-align:right; }
.match { font-size:19px; font-weight:600; letter-spacing:-.01em; }
.meta { font-size:12.5px; color:var(--muted); margin-top:3px; }
.verdict { font-size:11px; letter-spacing:.09em; text-transform:uppercase; font-weight:700; text-align:right; }
.verdict.flagged{color:var(--accent)} .verdict.candidate{color:var(--warn)} .verdict.no_play{color:var(--faint)}
.price { font-size:12.5px; color:var(--muted); margin-top:4px; }

.body { padding:0 18px 18px; border-top:1px solid var(--rule); }

.findings { margin:16px 0 0; display:flex; flex-direction:column; gap:9px; }
.finding { display:grid; grid-template-columns:56px 1fr; gap:13px; align-items:start; }
.spark { font-size:19px; font-weight:700; text-align:right; font-variant-numeric:tabular-nums; }
.finding.signal .spark{color:var(--accent)} .finding.debunk .spark{color:var(--clay)}
.finding.context .spark{color:var(--faint)}
.claim { font-size:15px; line-height:1.42; }
.support { font-size:12.5px; color:var(--muted); margin-top:3px; display:flex; gap:12px; flex-wrap:wrap; }

h3 { font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--faint);
     margin:22px 0 8px; font-weight:700; }
table { border-collapse:collapse; width:100%; font-size:14px; }
td,th { text-align:left; padding:6px 12px 6px 0; border-bottom:1px solid var(--rule); vertical-align:top; }
th { font-size:10px; letter-spacing:.09em; text-transform:uppercase; color:var(--faint); font-weight:600; }
td.n, th.n { text-align:right; padding-right:0; font-variant-numeric:tabular-nums;
       font-family:ui-monospace,monospace; white-space:nowrap; }
.gap { color:var(--clay); font-size:13px; margin:4px 0 0; }
.tw { overflow-x:auto; }
footer { margin-top:34px; padding-top:14px; border-top:1px solid var(--rule);
         font-size:11.5px; color:var(--faint); line-height:1.8; }
.empty { padding:30px 0; color:var(--muted); }
"""


