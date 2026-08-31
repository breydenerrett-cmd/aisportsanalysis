"""Assemble a whole slate's briefing: dossiers, detectors, verdicts.

The one place that knows how a day's analysis is put together. The CLI renders
what this produces; detectors and the dashboard both stay ignorant of each other.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.analysis import matchup as matchup_mod
from src.analysis import prices as prices_mod
from src.analysis import relevance as relevance_mod
from src.analysis import synthesis as synthesis_mod
from src.detect import base as detect
from src.detect import dossier as dossier_mod
from src.pipeline import lineups as lineup_mod
from src.pipeline import mismatch
from src.pipeline import news as news_mod
from src.pipeline import rosterwatch
from src.pipeline import slate as slate_mod


def make_entry(dossier, findings=None, *, verdict="no_play", side=None,
              market=None, summary=None, scan=None) -> dict:
    """The one game-analysis entry: a dossier, its findings, and its
    synthesis, always together.

    This is the fix for the worst leak the SaaS audit found
    (docs/SAAS_APPLICATION_ARCHITECTURE.md §2.1): a renderer that computes
    synthesis for an entry that lacks it means two callers can hand the SAME
    game to the SAME renderer and get two DIFFERENT domain objects back,
    invisibly, depending on which one happened to populate the field.
    `build_slate` uses this for every game on a real slate; anything else
    that needs to hand a game to a renderer -- a test building a one-game
    slate by hand, a future caller -- should use it too, so "the entry for
    this game" means the same object no matter who assembles it.
    """
    findings = list(findings or [])
    entry = {
        "dossier": dossier,
        "findings": findings,
        "synthesis": synthesis_mod.synthesize(dossier, findings),
        "verdict": verdict,
        "side": side,
        "market": market,
        "summary": summary,
    }
    if scan is not None:
        entry["scan"] = scan
    return entry


def build_slate(games, store, pitcher_logs=None, prices_by_matchup=None,
                weather_by_pk=None, lineups_by_pk=None, bullpen_by_team=None,
                handedness=None, splits_by_pk=None, matchups_by_pk=None,
                travel_by_pk=None, arsenals=None, batter_arsenals=None,
                news_by_pk=None, matchup_depth_by_pk=None,
                price_improvement_by_key=None, price_boards_by_key=None,
                roster_events_by_pk=None,
                detectors=None, information_time=None) -> dict:
    """One briefing for one date.

    The scanner's verdict and the detectors run over the same dossier, so a
    verdict can never disagree with the facts shown beneath it -- they are
    computed from one snapshot of one game's information.
    """
    entries, notes = [], []

    # Matchup depth is derived from inputs this function already holds (the
    # posted lineups, the handedness cache, the pitch store), so it is built
    # here rather than passed in from every caller -- the CLI gets it for
    # free. One walk of the pitch store per slate, and none at all when no
    # lineup is posted. Tests (and any caller that wants control) inject
    # `matchup_depth_by_pk` instead, the same way news_by_pk is injected.
    if matchup_depth_by_pk is None:
        matchup_depth_by_pk = matchup_mod.depth_by_pk(
            games, lineups_by_pk, handedness)
    # The multi-book capture store, read ONCE per slate, as boards: one
    # capture instant per game, one row per book. Every price surface on a
    # card is derived from these same boards -- the price-improvement table
    # here, the stale_book detector via the dossier -- so a card cannot show
    # one book count in a finding and a different one in its price table
    # (docs/OVERNIGHT_RUN.md, 2026-08-31, write-up #4). Tests inject either
    # mapping the same way. A store that does not exist yet simply yields no
    # boards, and every dossier then carries the honest gap instead.
    if price_boards_by_key is None:
        price_boards_by_key = prices_mod.boards_by_matchup()
    if price_improvement_by_key is None:
        price_improvement_by_key = prices_mod.by_matchup(
            boards=price_boards_by_key)
    # What changed since our own last look, scored for pre-event relevance.
    # Derived here, like matchup depth and the price boards, so the CLI gets
    # it for free and every caller sees the same point-in-time filter. Tests
    # inject `roster_events_by_pk` the same way.
    if roster_events_by_pk is None:
        roster_events_by_pk = what_changed_by_pk(
            games, information_time=information_time)
    for game in games:
        key = (game.get("away_team"), game.get("home_team"))
        # Both price stores are filed under canonical abbreviations, so the
        # lookup has to canonicalise too -- the schedule's ATH/AZ otherwise
        # miss boards filed under OAK/ARI, and the card reports "no board"
        # while the store holds eleven books.
        price_key = prices_mod.matchup_key(
            game.get("away_team"), game.get("home_team"), game.get("date"))
        dossier = dossier_mod.build(
            game, store,
            pitcher_logs=pitcher_logs,
            prices=(prices_by_matchup or {}).get(key),
            weather=(weather_by_pk or {}).get(game.get("game_pk")),
            lineups=_lineup_section(
                (lineups_by_pk or {}).get(game.get("game_pk")), handedness, game,
                batter_arsenals),
            splits=(splits_by_pk or {}).get(game.get("game_pk")),
            matchups=(matchups_by_pk or {}).get(game.get("game_pk")),
            travel=(travel_by_pk or {}).get(game.get("game_pk")),
            arsenals=_arsenal_section(game, arsenals),
            news=(news_by_pk or {}).get(game.get("game_pk")),
            matchup_depth=(matchup_depth_by_pk or {}).get(game.get("game_pk")),
            price_improvement=(price_improvement_by_key or {}).get(price_key),
            price_board=(price_boards_by_key or {}).get(price_key),
            roster_events=(roster_events_by_pk or {}).get(game.get("game_pk")),
            bullpen={team: (bullpen_by_team or {}).get(team) for team in key
                     if (bullpen_by_team or {}).get(team)} or None,
            information_time=information_time,
        )
        findings = detect.run_all(dossier, detectors)
        scan = mismatch.scan_game(game, dossier.get("teams"), dossier.get("starters"))

        # Stage two, using the price for the market the scan actually routed to.
        # Fetching first-five prices and then never screening with them left the
        # briefing permanently stuck on "candidate" -- it could describe a game
        # but never reach a verdict on one.
        if scan["verdict"] == mismatch.CANDIDATE:
            quote = _routed_price(dossier, scan["market"])
            scan = mismatch.apply_market_screen(
                scan, quote.get("away_price"), quote.get("home_price"))

        # The top block of the card -- the same dossier and the same
        # findings, ranked down to the few worth saying out loud -- is built
        # by make_entry, unconditionally, so the ledger and any other
        # consumer of a slate sees the identical summary the page shows.
        entries.append(make_entry(
            dossier, findings, verdict=scan["verdict"], side=scan.get("side"),
            market=scan.get("market"), summary=scan.get("summary"),
            scan=scan))

    unavailable = sum(1 for e in entries
                      if e["verdict"] == mismatch.MARKET_UNAVAILABLE)
    if unavailable:
        notes.append(
            f"{unavailable} game(s) cleared the talent bar but had no price on "
            "the market they were routed to. That is a different result from no "
            "play, and it is common: measured on three seasons, more than a "
            "third of flagged games have no first-five market at all.")

    if not any(e["verdict"] not in (mismatch.NO_PLAY, mismatch.MARKET_UNAVAILABLE)
               for e in entries) and entries:
        notes.append(
            "No play on the whole slate. That is the normal case, not a failure "
            "of the scan -- two roughly major-league teams playing a close game "
            "is what most of a major-league day looks like.")

    return {
        "date": games[0].get("date") if games else None,
        "games": entries,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# What changed: roster-watch events, matched to a game and scored
# ---------------------------------------------------------------------------

def what_changed_by_pk(games, information_time=None, *, events=None,
                       transactions=None, watch_dir=rosterwatch.DEFAULT_WATCH_DIR,
                       news_store=news_mod.DEFAULT_STORE, index=None) -> dict:
    """{game_pk: section} of roster events for that game's teams, scored.

    THREE RULES, ALL OF THEM ABOUT NOT LYING TO THE READER
    ------------------------------------------------------
    1. An event reaches exactly the game it belongs to. A lineup, probable or
       hitter event carries its own `game_pk`, which names one game on one
       slate; a transaction carries none, so it is matched by the club the
       move is about AND the official date MLB filed it under. Matching a
       transaction on team alone would put yesterday's call-up on today's
       card as though it had just happened.
    2. An event our poller only saw AFTER the briefing's information time
       does not appear. Point-in-time is not only a property of the model's
       features: a card that shows a 19:40 scratch under a 17:00 information
       time is a card that could not have been produced at 17:00.
    3. A game with nothing to say gets no entry at all, so the card renders
       no section rather than an empty box. Silence here is the ordinary
       case and does not need a heading to announce itself.

    The relevance index (one walk of the pitch store) is built ONLY when at
    least one event actually matched, so a quiet slate costs nothing.
    """
    if not games:
        return {}
    cutoff = _information_cutoff(information_time)
    events = rosterwatch.events(watch_dir) if events is None else events
    events = [e for e in events or [] if _seen_at_or_before(e, cutoff)]
    if not events:
        return {}

    by_pk = {g.get("game_pk"): g for g in games if g.get("game_pk") is not None}
    records = None
    if any(e.get("class") == rosterwatch.TRANSACTION_SEEN for e in events):
        if transactions is None:
            transactions = {row.get("transaction_id"): row
                            for row in news_mod.read(news_store)}
        records = transactions

    # (game_pk, event) pairs. One event can only ever land on one game.
    matched = []
    for event in events:
        game_pk = event.get("game_pk")
        if game_pk is not None:
            if game_pk in by_pk:
                matched.append((game_pk, event, None))
            continue
        record = (records or {}).get(event.get("transaction_id"))
        if not record:
            # Without the parsed feed record the move names no club and no
            # date, so there is no game it can honestly be attached to.
            continue
        target = _game_for_transaction(games, record)
        if target is not None:
            matched.append((target.get("game_pk"), event, record))
    if not matched:
        return {}

    slate_date = games[0].get("date")
    scores = relevance_mod.score_events(
        [event for _, event, _ in matched], slate_date, index=index,
        transactions={r.get("transaction_id"): r
                      for _, _, r in matched if r})
    sections = {}
    for (game_pk, event, record), score in zip(matched, scores):
        entry = sections.setdefault(game_pk, {
            "cutoff": slate_date,
            "information_time": cutoff.isoformat(),
            "not_an_edge": relevance_mod.NOT_AN_EDGE,
            "events": []})
        entry["events"].append(_rendered_event(
            event, score, by_pk.get(game_pk) or {}, record))
    for entry in sections.values():
        entry["events"].sort(key=lambda item: item.get("seen_utc") or "")
    return sections


def _rendered_event(event, score, game, record) -> dict:
    """One event as a reader meets it: what happened, how much it could matter,
    and the record behind that -- with the bracket it was observed in."""
    start, end = (event.get("interval") or (None, None))
    return {
        "class": event.get("class"),
        "headline": _event_headline(event, game, record),
        "tier": score.get("tier"),
        "tier_sentence": relevance_mod.tier_sentence(score),
        "basis": relevance_mod.basis_lines(score),
        "reasons": score.get("reasons") or [],
        "unknown_reason": score.get("unknown_reason"),
        "seen_utc": end,
        "timing": (f"observed between our polls at {start} and {end}"
                   if start else
                   f"first seen at {end}; no earlier poll of ours bounds when "
                   "it actually happened"),
        "inadmissible": bool(event.get("inadmissible")),
        "summary": relevance_mod.what_changed(score),
    }


def _event_headline(event, game, record) -> str:
    """The event in plain English, naming the club it belongs to.

    Player ids rather than names for the watch-store classes: the stores keep
    ids, and inventing a name we do not hold would be the one kind of
    confidence this page never fabricates.
    """
    event_class = event.get("class")
    detail = event.get("detail") or {}
    side = detail.get("side")
    team = game.get(f"{side}_team") if side else None
    who = f"{team}: " if team else ""
    if event_class == rosterwatch.STARTER_SCRATCH:
        return (f"{who}the listed starter changed from player "
                f"{detail.get('from')} to player {detail.get('to')}")
    if event_class == rosterwatch.HITTER_SCRATCH:
        removed = ", ".join(str(p) for p in detail.get("removed") or [])
        return (f"{who}the posted lineup lost listed hitter(s) {removed}")
    if event_class == rosterwatch.LINEUP_POSTED:
        return f"{who}the lineup was posted"
    if event_class == rosterwatch.TRANSACTION_SEEN:
        if record:
            return news_mod.sentence(record)
        return "a roster move was seen"
    return "a roster event was seen"


def _game_for_transaction(games, record):
    """The one game this move belongs to: same club, same official date.

    MLB dates a transaction by the day it took effect, and that day is the
    only slate it can be news for. A move dated yesterday is roster history
    and is already covered by the ten-day news section.
    """
    team = record.get("team")
    when = str(record.get("date") or "")[:10]
    if not team or not when:
        return None
    for game in games:
        if str(game.get("date") or "")[:10] != when:
            continue
        if team in (game.get("away_team"), game.get("home_team")):
            return game
    return None


def _information_cutoff(information_time):
    """The instant the briefing claims to know things as of, in UTC."""
    if information_time is None:
        return datetime.now(timezone.utc)
    if isinstance(information_time, datetime):
        moment = information_time
    else:
        moment = datetime.fromisoformat(
            str(information_time).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _seen_at_or_before(event, cutoff) -> bool:
    """Did we see this event by the information time? An unparseable stamp is
    treated as unseen -- absence over a guess in the direction that could
    show a reader something the briefing could not have known."""
    end = (event.get("interval") or (None, None))[1]
    if not end:
        return False
    try:
        seen = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return False
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return seen <= cutoff


def _arsenal_section(game, arsenals):
    """Each starter's arsenal, most-used pitch first."""
    if not arsenals:
        return None
    section = {}
    for side, key in (("away", "away_probable_id"), ("home", "home_probable_id")):
        rows = arsenals.get(str(game.get(key)))
        if rows:
            section[side] = rows
    return section or None


def _lineup_section(posted, handedness, game, batter_arsenals=None):
    """Posted lineup plus the platoon composition it presents to each starter."""
    if not posted:
        return None
    section = {}
    # A lineup's platoon composition is only meaningful against the hand of the
    # pitcher it actually faces, so each side is paired with the OPPOSING
    # starter. Crossing these over is the sort of mistake that produces a
    # confident, precisely wrong number on every game.
    for side, opposing_starter in (("away", "home_probable_id"),
                                   ("home", "away_probable_id")):
        slots = posted.get(side) or []
        pitcher_id = game.get(opposing_starter)
        throws = ((handedness or {}).get(str(pitcher_id)) or {}).get("throws")
        section[side] = {
            "batters": slots,
            "handedness": lineup_mod.lineup_handedness(slots, handedness or {}),
            "platoon_advantage": lineup_mod.platoon_advantage_share(
                slots, handedness or {}, throws),
            "faces_starter_throwing": throws,
            # Each hitter's measured line against each pitch type, grouped by
            # pitch so a detector can ask one question of the whole lineup.
            "vs_pitch": _lineup_vs_pitch(slots, batter_arsenals),
        }
    return section


def _lineup_vs_pitch(slots, batter_arsenals):
    grouped = {}
    for slot in slots or []:
        for row in (batter_arsenals or {}).get(str(slot.get("person_id")), []):
            grouped.setdefault(row.get("pitch_type"), []).append(
                dict(row, batter=slot.get("name")))
    return grouped


def _routed_price(dossier, market):
    """The moneyline for the market a scan was routed to.

    Screening a first-five routing against a full-game price compares two
    different quantities -- the first-five price is conditional on no push --
    so the market is chosen by the routing rather than by what happens to be
    available.
    """
    section = dossier.get("market") or {}
    key = ("h2h_1st_5_innings" if market == mismatch.MARKET_F5 else "h2h")
    return (section.get("markets") or {}).get(key) or {}
