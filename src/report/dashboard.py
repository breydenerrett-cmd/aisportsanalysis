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

import src.analysis as analysis
from src.analysis import synthesis as synthesis_mod
from src.detect import base as detect

# The one sentence a pairing with no real game carries on its starter and
# lineup sections. Defined by the analyze command (src/cli.py); duplicated here
# because the report layer cannot import the CLI that imports it, and pinned
# equal by tests/test_report_dashboard.py. It is the ONLY marker that reaches
# the renderer saying "this matchup never happened", and the card has to say so
# above the fold rather than leaving it buried in the missing-data list.
HYPOTHETICAL_GAP = "hypothetical matchup: no posted lineup or probable exists"

# What this system currently knows, said plainly and first. Anyone reading this
# page should know it before they read a single claim, because the claims are
# individually true and collectively unproven, and that distinction is the whole
# product.
#
# The count comes from src.analysis and nowhere else. This banner used to say
# "Thirteen" -- the V1-only figure -- while every game card below it said 27,
# so one page stated two counts of the same fact. See the note in
# src/analysis/__init__.py.
_STANDING = (
    "<b>Nothing on this page is a proven edge.</b> "
    f"{analysis.HYPOTHESES_TESTED_WORD} pre-registered hypotheses across "
    f"{analysis.HYPOTHESIS_FAMILIES_WORD} research families have been measured "
    "against outcomes and none cleared the bar. What follows is accurate "
    "description of tonight&rsquo;s games, the way a sharp friend would lay "
    "them out &mdash; every number with the sample it rests on, or an explicit "
    "note that it has none &mdash; useful for deciding what to look at and for "
    "knowing which of your own reasons are noise. It is not a model that "
    "beats the market."
)

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


# ---------------------------------------------------------------------------
# Per-game permalinks
# ---------------------------------------------------------------------------
#
# An anchor has to name the GAME, not its position in a list. `#game-3` moves
# to a different matchup the moment a postponement drops a game from the slate,
# so a link someone saved yesterday quietly points at the wrong card today. The
# id is therefore derived from the two clubs and the official date -- the three
# facts that identify the game itself -- and is byte-identical across rebuilds
# of the same slate.
#
# Doubleheaders are the one case where those three facts do not separate two
# games, so the tie is broken with another intrinsic fact (MLB's game number,
# or failing that its game_pk) rather than with the card's ordinal.

ANCHOR_PREFIX = "game-"


def _slug(value) -> str:
    """A URL-fragment-safe token. Never empty, so an id is never bare."""
    out = "".join(ch if ch.isalnum() else "-" for ch in str(value or ""))
    out = "-".join(part for part in out.split("-") if part)
    return out or "x"


def _anchor_base(game) -> str:
    return (f"{ANCHOR_PREFIX}{_slug(game.get('away'))}-"
            f"{_slug(game.get('home'))}-{_slug(game.get('date'))}")


def _assign_anchors(games) -> None:
    """Give every card a stable id, disambiguating only on intrinsic facts."""
    grouped = {}
    for game in games:
        grouped.setdefault(_anchor_base(game), []).append(game)
    for base, members in grouped.items():
        if len(members) == 1:
            members[0]["anchor"] = base
            continue
        # A doubleheader. Both halves are real games with the same clubs on the
        # same date, so each keeps a suffix that belongs to the game and not to
        # the page: MLB's own game number where we have it, else the game_pk.
        for game in members:
            marker = game.get("game_number") or game.get("game_pk")
            game["anchor"] = f"{base}-{_slug(marker)}" if marker else base
        # If even that did not separate them we would be emitting a duplicate
        # id, which is worse than an ugly one: the browser would send every
        # link to the first match. Fall back to a stated ordinal and say so.
        if len({g["anchor"] for g in members}) != len(members):
            for ordinal, game in enumerate(members, start=1):
                game["anchor"] = f"{base}-listed-{ordinal}"
                game["anchor_unstable"] = True


def _payload(slate, stamp) -> dict:
    games = []
    for entry in slate.get("games", []):
        dossier = entry["dossier"]
        findings = entry.get("findings", [])
        # The briefing computes this; a caller that assembles a slate by hand
        # (the analyze path, and every test that builds a one-game slate) gets
        # it here instead, from the same dossier and the same findings.
        summary = entry.get("synthesis")
        if summary is None:
            summary = synthesis_mod.synthesize(dossier, findings)
        games.append({
            "synthesis": _plain(summary),
            "away": dossier.game.get("away_team"),
            "home": dossier.game.get("home_team"),
            # Carried for the permalink: the official date of THIS game, which
            # for a card built by `analyze` can differ from nothing at all but
            # is still the fact the anchor is named after.
            "date": dossier.game.get("date") or slate.get("date"),
            "game_number": dossier.game.get("game_number"),
            "game_pk": dossier.game.get("game_pk"),
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
    _assign_anchors(games)
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


def _prob_pct(value) -> str:
    """A probability as a percentage, or "--". Never 0.0% for a missing one."""
    return "--" if value is None else f"{value:.1%}"


def _prob_points(value) -> str:
    """A probability DIFFERENCE, in win-probability points.

    The store keeps these as fractions (0.019). Rendering the fraction under a
    heading that says "points" understates it a hundredfold and puts it on a
    different scale from every detector sentence on the same page, which all
    say "N points of win probability". Two decimals is the honest resolution:
    the inputs are American prices, and a third digit is arithmetic noise.
    """
    return "--" if value is None else f"{value * 100:+.2f}"


def _return_pct(value) -> str:
    return "--" if value is None else f"{value:+.2f}%"


# Said whenever no side on a board beats the de-vigged consensus, which on a
# normally-priced board is every side. Without it a column of negatives reads
# as a verdict on the night instead of as the definition of the two numbers
# being subtracted.
NO_IMPROVEMENT_NOTE = (
    "No side here beats the de-vigged consensus, and that is the usual case "
    "rather than a bad board: the best available price still carries the "
    "book's vig while the consensus it is measured against has had the vig "
    "removed, so the difference is normally negative by roughly the hold. A "
    "positive number is the exception worth noticing; these are not.")


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
        # Same rule as the synthesis block: "sample 7-day window" names a
        # period, not an amount of evidence, and must not wear the word.
        if synthesis_mod.sample_size(finding["sample"]) is None:
            support.append('<span class="mono">no sample size stated &mdash; '
                           f'{_esc(finding["sample"])}</span>')
        else:
            support.append(
                f'<span class="mono">sample {_esc(finding["sample"])}</span>')
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
        # This block used to read "No detector found anything out of the
        # ordinary" whenever `picks` was empty. But `picks` excludes
        # context-kind findings, so the page said no detector found anything
        # while the card directly below listed a travel finding scored 2.0
        # standard units from normal. The lead now says only what it checked.
        context_count = sum(1 for game in games for finding in game["findings"]
                            if finding["kind"] == detect.CONTEXT)
        tail = (
            f' {context_count} context finding(s) did fire and are listed on '
            'the cards below; they describe the game rather than point at a '
            'side, which is why none of them is summarised here.'
            if context_count else
            ' No context finding fired either.')
        return (
            '<section class="lead"><h2>No side-pointing finding on this '
            'slate</h2>'
            '<p class="claim">No detector produced a finding that points at a '
            'side or a total. That is the normal case, not a failure &mdash; '
            'most days of major-league baseball are two roughly major-league '
            f'teams playing a close game.{_esc(tail)}</p></section>')

    rows = []
    for index, game, finding in picks[:6]:
        rows.append(
            f'<a class="leaditem" href="#{_esc(game["anchor"])}">'
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


def _suppressed_section(game) -> str:
    """What synthesis considered and cut, with its own reason, collapsed.

    The ranking throws things away for honest reasons -- no sample attached, no
    comparable scale, a duplicate of a better-stated version of the same fact,
    outside the top five. Computing that trail and then hiding it made the
    summary look like everything the system had to say. It is collapsed because
    it is an audit trail rather than a read, and every reason is printed exactly
    as synthesis wrote it: nothing here is summarised, ranked or invented.
    """
    summary = game.get("synthesis") or {}
    cut = [item for item in (summary.get("suppressed") or [])
           if isinstance(item, dict)]
    if not cut:
        return ""
    rows = []
    for item in cut:
        statement = item.get("statement")
        reason = item.get("reason")
        rows.append(
            '<div class="cutitem">'
            f'<div class="claim">{_esc(statement) if statement else "&mdash;"}</div>'
            '<div class="support">'
            + (f'{_esc(reason)}' if reason else 'no reason recorded')
            + '</div></div>')
    return ('<details class="cut"><summary>What was left out, and why '
            f'({len(cut)})</summary>'
            f'<div class="cutlist">{"".join(rows)}</div></details>')


def _synthesis_section(game) -> str:
    """The top block: the three-to-five things that matter, or the no-edge line.

    It sits above every other section on the card because a reader who stops
    after one block should have read the most important thing rather than the
    first thing. Nothing here is new information -- every item restates a
    number from a section below it, sample attached and evidence stamped -- so
    a reader who does not trust the summary can always go find the source.
    """
    summary = game.get("synthesis") or {}
    items = summary.get("items") or []
    if not items:
        return ('<div class="synth empty">'
                '<h3>What matters tonight</h3>'
                f'<p class="synthhead">{_esc(summary.get("headline") or synthesis_mod.NO_EDGE_HEADLINE)}</p>'
                f'<p class="leadnote">{_esc(summary.get("note") or "")}</p>'
                f'{_suppressed_section(game)}'
                '</div>')
    rows = []
    for rank, item in enumerate(items, start=1):
        # The page's header promises every number carries the sample it rests
        # on. Some detector "samples" name an elapsed period rather than an
        # amount of play -- "7-day window", "since SF, 3 day(s) ago" -- and
        # synthesis already refuses to count those as denominators. Labelling
        # them "sample" anyway borrowed credibility they do not have, so the
        # word is reserved for strings that actually name a countable amount.
        if item.get("sample_n") is None:
            support = ['<span class="mono">no sample size stated &mdash; '
                       f'{_esc(item.get("sample"))}</span>']
        else:
            support = [f'<span class="mono">sample {_esc(item.get("sample"))}</span>']
        if item.get("below_floor"):
            support.append('<span class="mono">below this section&rsquo;s '
                           'sample floor</span>')
        support.append(f'<span class="chip {_esc(item.get("evidence"))}" '
                       f'title="{_esc(item.get("evidence_meaning"))}">'
                       f'{_esc(item.get("evidence_label"))}</span>')
        rows.append(
            f'<div class="synthitem">'
            f'<div class="synthrank">{rank}</div>'
            f'<div><div class="claim">{_esc(item.get("statement"))}</div>'
            f'<div class="support">{"".join(support)}'
            f'<span class="mono">{_esc(item.get("source"))}</span>'
            f'</div></div></div>')
    return ('<div class="synth"><h3>What matters tonight</h3>'
            f'<div class="synthlist">{"".join(rows)}</div>'
            f'<p class="leadnote">{_esc(summary.get("note") or "")}</p>'
            f'{_suppressed_section(game)}</div>')


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

    # Which side is thin, not merely that one is: the splits table below shows
    # per-split OPS for BOTH starters, so a blanket "his rates are suppressed"
    # sentence was false the moment a thin starter had splits rows. It sat
    # directly under a table quoting him at .535 OPS on 23 batters faced.
    thin_sides = [side for side in ("away", "home")
                  if starters.get(f"{side}_sp_thin")]
    thin_teams = [game[side] for side in thin_sides]

    splits = game["sections"].get("splits") or {}
    split_rows = []
    for side, team in (("away", game["away"]), ("home", game["home"])):
        record = ((splits.get(side) or {}).get("record") or {}).get("splits") or {}
        for key in ("Home Games", "Away Games", "vs Left", "vs Right"):
            row = record.get(key)
            if row:
                mark = " (small sample)" if side in thin_sides else ""
                split_rows.append([f"{team} — {key}{mark}", _num(row.get("ops"), 3),
                                   row.get("batters_faced") or "--",
                                   row.get("innings") or "--"])
    thin_has_splits = any(
        ((splits.get(side) or {}).get("record") or {}).get("splits")
        for side in thin_sides)
    if split_rows:
        parts.append("<h3>Starter splits (OPS allowed)</h3>")
        parts.append(_table(split_rows, ["split", "OPS", "BF", "IP"]))
    if thin_sides or starters.get("either_sp_thin"):
        who = " and ".join(_esc(t) for t in thin_teams) or "One team"
        sentence = (
            f'{who}&rsquo;s starter is under the innings threshold, so the '
            'season rate line for him in the table above is withheld rather '
            'than shown &mdash; a rate off that few innings is noise.')
        if thin_has_splits:
            # Say what the page actually does, not what it wishes it did.
            sentence += (' His rows in the splits table ARE shown, marked '
                         '&ldquo;small sample&rdquo;: read each against the '
                         'batters-faced figure beside it, which is the whole '
                         'sample that row rests on.')
        parts.append(f'<p class="gap">{sentence}</p>')
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
                f'Unusually, a sample large enough to be worth a sentence '
                f'&mdash; supporting evidence, never a read on its own.</p>')
        else:
            parts.append(f'<p class="gap">{_esc(entry.get("reason") or "sample too small")}</p>')
    return "".join(parts)


def _matchup_depth_section(game) -> str:
    """The unit-vs-specific-weakness decomposition, sentences first.

    Everything in it is an observation of play before a stated cutoff --
    the section says so itself -- and every number arrives with its sample.
    Small-sample warnings and absences render in the gap style so a thin or
    missing read can never be mistaken for a solid one.
    """
    depth = game["sections"].get("matchup_depth")
    if not depth:
        return _gap_block("Matchup depth",
                          game["gaps"].get("matchup_depth", "not built"))
    parts = ["<h3>Matchup depth</h3>"]
    note = _esc(depth.get("nature") or "")
    if depth.get("cutoff"):
        note += f" Cutoff: pitches before {_esc(depth['cutoff'])}."
    if note:
        parts.append(f'<p class="support">{note}</p>')
    # The stuff intro carries the mechanism once and the V5 no-edge note --
    # section-level on purpose, so no per-row sentence repeats either.
    if depth.get("stuff_note"):
        parts.append(f'<p class="support">{_esc(depth["stuff_note"])}</p>')
    for side, team in (("away", game["away"]), ("home", game["home"])):
        entry = depth.get(side)
        if not entry:
            continue
        throws = entry.get("opposing_starter_throws")
        parts.append(f'<h3>{_esc(team)} lineup vs '
                     f'{_esc(throws + "HP" if throws else "opposing starter")}'
                     "</h3>")
        if entry.get("reason"):
            parts.append(f'<p class="gap">{_esc(entry["reason"])}</p>')
            continue
        for name in ("handedness", "pitch_mix", "concentration",
                     "starter_stuff"):
            picture = entry.get(name) or {}
            for sentence in picture.get("sentences") or []:
                parts.append(f'<p class="support">{_esc(sentence)}</p>')
            for reason in picture.get("absent") or []:
                parts.append(f'<p class="gap">not available: {_esc(reason)}</p>')
            for warning in picture.get("warnings") or []:
                parts.append(f'<p class="gap">{_esc(warning)}</p>')
        batters = (entry.get("pitch_mix") or {}).get("batters") or []
        if batters:
            rows = [[f'{b.get("order")}. {b.get("name")}', b.get("pa"),
                     _num(b.get("woba"), 3)] for b in batters]
            parts.append(_table(rows, ["vs primary pitch", "PA", "wOBA"]))
    return "".join(parts)


def _price_improvement_section(game) -> str:
    """The best price on the board versus the consensus, labelled honestly.

    The label is part of the section, not decoration: this is line-shopping
    value -- a better execution price -- and the page never lets it read as
    expected value or a prediction.

    Two things this block used to get wrong, both of which flattered the
    number. The improvement column was headed "prob pts" while printing a
    probability FRACTION (-0.0056), so it read a hundred times smaller than
    the "1.9 points of win probability" a detector quotes on the same card.
    And a normally-vigged board makes every row negative by construction --
    the best price still carries vig, the consensus does not -- which the page
    never said, leaving a column of minus signs looking like a bad night
    rather than like arithmetic.
    """
    section = game["sections"].get("price_improvement")
    if not section:
        return _gap_block("Best price vs consensus",
                          game["gaps"].get("price_improvement",
                                           "no multi-book observations"))
    rows, any_positive = [], False
    for side in ("away", "home"):
        detail = (section.get("sides") or {}).get(side) or {}
        if detail.get("skipped"):
            rows.append(f'<tr><td>{side}</td><td colspan="4" class="gap">'
                        f'{_esc(detail["skipped"])}</td></tr>')
            continue
        price = detail.get("best_price")
        price_text = (f"+{price}" if isinstance(price, int) and price > 0
                      else str(price))
        points = detail.get("improvement_points")
        if points is not None and points > 0:
            any_positive = True
        rows.append(
            f'<tr><td>{side}</td>'
            f'<td class="mono">{_esc(price_text)} '
            f'({_esc(detail.get("best_book") or "?")})</td>'
            f'<td class="mono">{_prob_pct(detail.get("consensus_probability"))}</td>'
            f'<td class="mono">{_prob_points(points)}</td>'
            f'<td class="mono">{_return_pct(detail.get("improvement_return_pct"))}</td>'
            f'</tr>')

    dispersion = section.get("dispersion") or {}
    books = dispersion.get("books")
    spread = dispersion.get("home_probability_range")
    observed = section.get("observed_utc")
    # The capture instant matters: this board is ONE capture, and a detector
    # elsewhere on the card quotes its own book count from its own snapshot.
    # Without the timestamp the two counts read as one fact stated twice.
    when = (f" captured {observed}" if observed
            else " (capture instant not recorded)")
    parts = [
        '<h3>Best price vs consensus</h3>',
        '<table class="prices"><tr><th>side</th><th>best available</th>'
        '<th>consensus (de-vigged)</th>'
        '<th>improvement (win-prob points)</th>'
        '<th>improvement (return)</th></tr>',
        "".join(rows), '</table>',
        f'<p class="gap">{_esc(books if books is not None else "?")} books at '
        f'one instant{_esc(when)}; home-probability spread '
        f'{"--" if spread is None else f"{spread:.4f}"}. '
        f'{_esc(section.get("label") or "")}.</p>',
    ]
    if not any_positive:
        parts.append(f'<p class="gap">{_esc(NO_IMPROVEMENT_NOTE)}</p>')
    return "".join(parts)


def _what_changed_section(game) -> str:
    """Roster events for these two clubs since our own previous look.

    Renders NOTHING when there is nothing -- no heading, no empty box. Most
    slates are quiet and a section that announces its own silence on fifteen
    cards teaches the reader to skip it on the sixteenth.

    Every line carries three things and never fewer: what happened, how much
    it could plausibly matter (the pre-event relevance tier, with UNKNOWN
    spelled out as unknown rather than dressed as small), and the record that
    tier was computed from, denominators attached. The section states in its
    own words that a tier is description and not an edge.
    """
    section = game["sections"].get("what_changed")
    events = (section or {}).get("events") or []
    if not events:
        return ""
    rows = []
    for event in events:
        support = [f'<span class="mono">{_esc(event.get("tier_sentence"))}</span>']
        if event.get("inadmissible"):
            support.append('<span class="mono">first sighting &mdash; the '
                           'timing is unbounded (grade C)</span>')
        basis = "".join(f"<li>{_esc(line)}</li>"
                        for line in event.get("basis") or [])
        basis_html = (f'<ul class="basis">{basis}</ul>' if basis else
                      '<p class="gap">no pre-event record to show for this '
                      'event</p>')
        reasons = "".join(f'<div class="support">{_esc(reason)}</div>'
                          for reason in event.get("reasons") or [])
        rows.append(
            '<div class="changeitem">'
            f'<div class="claim">{_esc(event.get("headline"))}</div>'
            f'<div class="support">{"".join(support)}</div>'
            f'{reasons}{basis_html}'
            f'<div class="support mono">{_esc(event.get("timing"))}</div>'
            '</div>')
    cutoff = section.get("cutoff")
    note = ('Facts below are the player&rsquo;s own record from pitches '
            f'stored before {_esc(cutoff)}. ' if cutoff else "")
    return ('<h3>What changed</h3>'
            f'<p class="leadnote">{note}{_esc(section.get("not_an_edge") or "")}</p>'
            f'<div class="changelist">{"".join(rows)}</div>')


def _news_section(game) -> str:
    """What changed for either club in the last ten days.

    Placed directly under the findings and above the market, because it is the
    only section describing a CHANGE rather than a steady state, and a change is
    what a reader is most likely not to know yet.
    """
    news = game["sections"].get("news")
    if not news:
        return _gap_block("Recent roster news",
                          game["gaps"].get("news", "not fetched"))
    blocks = []
    for team in sorted(news):
        rows = news[team] or []
        if not rows:
            continue
        items = "".join(
            f'<li>{_esc(row.get("sentence") or row.get("description") or "")}'
            f'<span class="newsdate mono"> {_esc((row.get("date") or "")[:10])}</span></li>'
            for row in rows)
        blocks.append(f'<div class="newsteam"><h4>{_esc(team)}</h4>'
                      f'<ul class="news">{items}</ul></div>')
    if not blocks:
        return _gap_block("Recent roster news",
                          game["gaps"].get("news", "nothing in the window"))
    return ('<h3>Recent roster news</h3>'
            f'<div class="newsgrid">{"".join(blocks)}</div>')


def _teams_section(game) -> str:
    teams = game["sections"].get("teams")
    if not teams:
        return _gap_block("Teams", game["gaps"].get("teams"))
    # "Record" over a column holding only wins invited the reader to supply the
    # losses that were never there. The field is wins; the header says wins.
    fields = [("Wins", "wins", 0), ("Win %", "win_pct", 3),
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


def _is_hypothetical(game) -> bool:
    """Did this pairing never actually take the field?

    `analyze` will build a card for any two clubs on any date. When no real
    game exists it says so in the terminal and stamps the honest sentence on
    the starter and lineup sections -- and that was the ONLY place it appeared,
    at the bottom of a missing-data list. The saved HTML then read as an
    ordinary game card: a venue, a verdict, real season records, nothing at all
    saying the game is invented. The artifact outlives the terminal line, so
    the card has to carry the fact itself.
    """
    gaps = game.get("gaps") or {}
    return any(gaps.get(section) == HYPOTHETICAL_GAP
               for section in ("starters", "lineups"))


def _hypothetical_banner(game) -> str:
    if not _is_hypothetical(game):
        return ""
    return ('<p class="gap"><b>This game does not exist.</b> No such matchup '
            'was scheduled on this date, so there is no starter, no lineup and '
            'no market for it. The team and park numbers below are real and '
            'point-in-time; the pairing is not, and the verdict describes a '
            'game that was never played.</p>')


def _permalink(game) -> str:
    """A visible, copyable link to this one card.

    The anchor is worth showing rather than hiding behind a hover affordance:
    the whole point is that it can be copied out of the page and pasted into a
    message, and a reader cannot copy what is not on the screen. The sentence
    beside it states the guarantee -- same id on every rebuild of this date --
    because an id that silently moved would be worse than no link at all.
    """
    anchor = game.get("anchor")
    if not anchor:
        return ""
    if game.get("anchor_unstable"):
        note = ("this id could not be built from the clubs and the date alone "
                "and falls back to this card&rsquo;s position on the page, so "
                "it is NOT guaranteed stable across rebuilds")
    else:
        note = ("a stable link to this game &mdash; the same id every time "
                "this date is rebuilt")
    return (f'<p class="permalink"><a class="mono" href="#{_esc(anchor)}">'
            f'#{_esc(anchor)}</a> <span class="support">{note}</span></p>')


def _game_card(game) -> str:
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
        _permalink(game)
        + _hypothetical_banner(game)
        + _synthesis_section(game)
        + ('<h3>Why this game is interesting</h3>'
         f'<div class="findings">{findings}</div>' if findings else
         '<h3>Why this game is interesting</h3>'
         '<p class="gap">No detector had anything to say about this game.</p>')
        + _what_changed_section(game)
        + _news_section(game)
        + _market_section(game) + _price_improvement_section(game) + _starters_section(game)
        + _lineups_section(game) + _matchup_section(game)
        + _matchup_depth_section(game)
        + _teams_section(game) + _environment_section(game)
        + _gaps_section(game))

    # <details> is native expand/collapse. No script, so it works in a sandboxed
    # preview, with a strict CSP, or with scripting switched off entirely.
    return (
        f'<details class="game {_esc(verdict)}" id="{_esc(game.get("anchor"))}"'
        f'{" open" if game.get("open") else ""}>'
        f'<summary class="gamehead">'
        f'<div><div class="match">{_esc(game["away"])} @ {_esc(game["home"])}'
        f'{" — HYPOTHETICAL, never played" if _is_hypothetical(game) else ""}</div>'
        f'<div class="meta">{_esc(meta)}</div>'
        f'<div class="meta">{_esc(game.get("summary") or "")}</div></div>'
        f'<div class="headright">'
        f'<div class="verdict {_esc(verdict)}">'
        f'{_esc(VERDICT_LABELS.get(verdict, verdict))}</div>{price_html}</div>'
        f'</summary><div class="body">{body}</div></details>')


# The machine-readable summary the archive index reads back. It is an HTML
# COMMENT, not a script and not a data attribute: the page must keep working
# with scripting off (see the module docstring), and a comment adds nothing a
# browser will render. The archive parses this when it is present and falls
# back to reading the visible markup when it is not, so briefings written
# before this existed still appear in the index instead of vanishing.
INDEX_MARKER = "briefing-index"


def _index_comment(payload) -> str:
    record = {
        "date": payload.get("date"),
        "generated_at": payload.get("generated_at"),
        "counts": payload.get("counts") or {},
        "findings": sum(len(g.get("findings") or []) for g in payload["games"]),
        "games": [{
            "anchor": g.get("anchor"),
            "away": g.get("away"),
            "home": g.get("home"),
            "verdict": g.get("verdict"),
            "headline": (g.get("synthesis") or {}).get("headline"),
        } for g in payload["games"]],
    }
    # A JSON string may legitimately contain "--", which cannot appear inside an
    # HTML comment without risking an early close. Escaping the hyphens as JSON
    # unicode escapes keeps the payload byte-for-byte parseable while making
    # "-->" unconstructible from the data.
    blob = json.dumps(record, sort_keys=True).replace("--", "\\u002d\\u002d")
    return f"<!--{INDEX_MARKER} {blob}-->"


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

    cards = "".join(_game_card(g) for g in games) or (
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
{_index_comment(payload)}
<div class="wrap">
<header>
<h1>Slate briefing &mdash; {_esc(payload.get("date"))}</h1>
<div class="sub mono">generated {_esc(payload["generated_at"])} &middot; times in UTC</div>
<div class="counts">{tiles}</div>
<div class="standing">{_STANDING}</div>
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

.newsgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
  gap:14px; margin:10px 0 4px; }
.newsteam h4 { margin:0 0 6px; font-size:12px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--faint); }
ul.news { margin:0; padding-left:18px; }
ul.news li { margin-bottom:5px; font-size:14px; line-height:1.45; }
.newsdate { color:var(--faint); font-size:11px; white-space:nowrap; }
.changelist { display:flex; flex-direction:column; gap:12px; margin-top:8px; }
.changeitem { border-left:3px solid var(--rule); padding-left:12px; }
ul.basis { margin:5px 0 0; padding-left:18px; }
ul.basis li { font-size:12.5px; color:var(--muted); line-height:1.45; }
.standing { margin:18px 0 0; padding:12px 14px; border-left:3px solid var(--clay);
  background:var(--sunk); font-size:13px; line-height:1.5; color:var(--muted); }
.standing b { color:var(--ink); }
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

.permalink { margin:12px 0 0; font-size:12.5px; display:flex; gap:10px;
             align-items:baseline; flex-wrap:wrap; }
.permalink a { color:var(--accent); text-decoration:none; word-break:break-all; }
.permalink a:hover { text-decoration:underline; }
.permalink .support { margin:0; color:var(--faint); }

.synth { margin:16px 0 4px; padding:14px 16px 10px; background:var(--sunk);
         border:1px solid var(--rule); border-radius:4px; }
.synth h3 { margin-top:0; }
.synthlist { display:flex; flex-direction:column; gap:11px; }
.synthitem { display:grid; grid-template-columns:26px 1fr; gap:10px; align-items:baseline; }
.synthrank { font-size:13px; font-weight:700; color:var(--faint);
             font-variant-numeric:tabular-nums; }
.synthhead { font-size:15px; line-height:1.42; margin:0 0 6px; }
.synth .leadnote { margin:12px 0 0; }
.synth .chip.observed { color:var(--accent); }
.synth .chip.tested_null { color:var(--clay); }
.cut { margin:10px 0 2px; border-top:1px solid var(--rule); padding-top:8px; }
.cut > summary { cursor:pointer; font-size:12.5px; color:var(--faint); }
.cutlist { display:flex; flex-direction:column; gap:8px; margin-top:9px; }
.cutitem .claim { font-size:13px; color:var(--muted); }
.cutitem .support { font-size:12px; color:var(--faint); }

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


