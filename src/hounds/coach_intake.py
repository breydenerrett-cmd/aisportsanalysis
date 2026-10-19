"""python -m src.hounds.coach_intake : turn the weekly coach Zap's GitHub issues into challengers.

THE CHAIN. A Zap fetches ``GET /hounds/coach-brief``, an AI step answers with one JSON object, and the Zap
files a GitHub issue (label ``coach-proposal``, body = that JSON in a ```json fence) as the owner. This
module reads the open issues with that label, hands each valid one to ``proposals.propose_pack`` exactly as
the operator CLI does (``python -m src.hounds.learning propose``: same graded count, same coach switch, same
guards), then comments the outcome on the issue, labels it and closes it. A proposal creates a CHALLENGER
that runs in shadow; the pre-registered referee alone can ever promote it.

EVERYTHING IN AN ISSUE IS UNTRUSTED DATA. The issue body is text written by a model, and anyone who can
edit an issue can change it. So:

  * only issues whose author login is the owner's are read at all; any other author is "ignored" (commented,
    labelled, closed) and its body is never parsed;
  * the FIRST ```json fence is parsed with ``json.loads`` and NOTHING else is looked at: not the title, not
    the prose around the fence, not later fences. Only four fields are taken from it (hound, params,
    hypothesis, evidence); any other key is dropped unread;
  * nothing from an issue is ever executed, evaluated, formatted into a command or followed. ``gh`` is run
    with an argument LIST (no shell), the hound id and every other value reach only the same validators a
    hand-typed ``propose`` reaches, and text echoed back into a comment is stripped and length-capped;
  * the proposal's own guards (knob bounds and grid, text alphabet, evidence shape, caps, cooldown,
    near-duplicates) are the gate; this module adds no rule of its own beyond "owner, one JSON block".

OUTCOMES (one comment, one label, closed unless noted)

  accepted     "accepted: challenger <id> now runs in shadow; the referee decides"   label coach-accepted
  refused      "refused: <code> <message>"                                         label coach-refused
  ignored      "ignored: not from the owner account"                               label coach-refused
  waiting      the coach switch is off or the loop is paused: a comment says so and the issue stays OPEN,
               so it runs once the owner flips the switch. The comment is posted once, not every run.

``--dry-run`` prints what would happen. It makes no ``gh`` write (comment, label, close, label create) and
no ledger write: the proposal is tried against a throwaway COPY of the learning ledger, so the answer is the
real one and the real chain is untouched.

SEAMS. ``main(argv, runner=...)``: the ``gh`` runner (``Runner``: argument list in, ``(returncode, stdout,
stderr)`` out) is injected, so tests use a fake and never touch the network. ``--root`` / ``--champion-ledger``
/ ``--coach-config`` / ``--now`` are the CLI's own testing seams.

WHERE IT RUNS. The ``gh`` path (comment, label, close) is local only: every workflow's GITHUB_TOKEN has
contents (and actions) permission only, no ``issues``, so a runner could not comment, label or close. It runs
where ``gh`` is signed in as the owner (docs/ZAPS.md). It reads and writes the same ledger as the capture slots,
so pull before and push right after: a rejected push loses the proposal while its issue is already closed.

THE PRACTICE LANE (docs/COACH_REPORT_CARD.md, 2026-10-18). ``--source api`` is the READ-ONLY path that runs in
the capture slot on GitHub Actions with no token: the repository is public, so
``GET /repos/<owner>/<repo>/issues?labels=coach-proposal&state=all`` answers anonymously (``GITHUB_TOKEN``, if
present, is sent only to raise the rate limit). It never comments, labels or closes; instead every issue is
recorded exactly once, by number, in ``evidence/hounds_coach_v1.jsonl`` (``coach_card``): a valid suggestion
becomes a practice row (and ALSO a real shadow challenger when the pre-registered guards accept it), an invalid
one becomes a ``coach_refused`` row with the reason. ``--grade`` then runs ``coach_grade`` (hindsight and the
live shadow comparison). Everything in an issue is still untrusted data; the same fence rule applies.
``--source fixture --file F`` reads issues from a JSON file and exists for tests only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src.hounds import coach_card
from src.hounds.learning import coach_brief, proposals, rules, tunables
from src.hounds.learning import ledger as L

REPO = "breydenerrett-cmd/aisportsanalysis"
OWNER_LOGIN = "breydenerrett-cmd"
PROPOSED_BY = "zapier-coach"

LABEL_PROPOSAL = "coach-proposal"
LABEL_ACCEPTED = "coach-accepted"
LABEL_REFUSED = "coach-refused"
LABELS = {LABEL_ACCEPTED: ("0e8a16", "A coach proposal that became a shadow challenger"),
          LABEL_REFUSED: ("b60205", "A coach proposal that was refused or ignored")}

MAX_ISSUES = 50
MAX_BODY_CHARS = 20_000            # a real proposal is under 2 KB; a huge body is not one
MAX_ECHO_CHARS = 400               # what of a refusal message is written back into a comment
GH_TIMEOUT_S = 60

# ```json ... ``` : the FIRST fence whose info string is exactly json (any case). Lazy, so the first closing
# fence ends it. The body of a fence is data to json.loads, never to anything else.
_FENCE = re.compile(r"```[ \t]*json[ \t]*\r?\n(.*?)\r?\n?```", re.IGNORECASE | re.DOTALL)

Runner = Callable[[Sequence[str]], tuple]


class IntakeError(Exception):
    """A refusal that is not the proposal's own: ``code`` is stable, the message is plain."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# ---- gh ----------------------------------------------------------------------------------------------

def gh_binary() -> str:
    """``$GH_BIN``, else ``gh`` on PATH, else the Windows installer's default location, else plain ``gh``
    (which then fails with a clear 'not found' the run reports)."""
    explicit = (os.environ.get("GH_BIN") or "").strip()
    if explicit:
        return explicit
    found = shutil.which("gh")
    if found:
        return found
    windows = Path(r"C:\Program Files\GitHub CLI\gh.exe")
    return str(windows) if windows.exists() else "gh"


def default_runner(args: Sequence[str]) -> tuple:
    """Run ``gh`` with an argument list (never a shell). ``(returncode, stdout, stderr)``."""
    try:
        done = subprocess.run([gh_binary(), *args], capture_output=True, text=True, encoding="utf-8",
                              timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return done.returncode, done.stdout, done.stderr


# ---- reading an issue ----------------------------------------------------------------------------------

def parse_proposal(body) -> dict:
    """The four proposal fields from an issue body, or ``IntakeError``.

    Takes the first ```json fence, ``json.loads`` it, and returns ``{hound, params, hypothesis, evidence}``
    with nothing else. The shapes are only those ``propose_pack`` needs to be callable; its own validators
    judge the values."""
    if not isinstance(body, str) or not body.strip():
        raise IntakeError("no_json_block", "the issue has no ```json block")
    match = _FENCE.search(body[:MAX_BODY_CHARS])
    if match is None:
        raise IntakeError("no_json_block", "no ```json block found in the issue body")
    try:
        data = json.loads(match.group(1))
    except ValueError:
        raise IntakeError("bad_json", "the ```json block is not valid JSON") from None
    if not isinstance(data, dict):
        raise IntakeError("bad_json", "the ```json block must be one JSON object")
    hound, params = data.get("hound"), data.get("params")
    if not isinstance(hound, str) or not hound.strip():
        raise IntakeError("bad_fields", "hound must be a hound id (text)")
    if not isinstance(params, dict):
        raise IntakeError("bad_fields", "params must be an object of knob values")
    return {"hound": hound.strip(), "params": params, "hypothesis": data.get("hypothesis"),
            "evidence": data.get("evidence")}


def _echo(text) -> str:
    """Text made safe to write back into a GitHub comment: control characters out, ``@`` out (no mention),
    one line, capped."""
    squashed = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text)).split()).replace("@", "")
    return squashed[:MAX_ECHO_CHARS]


def is_owner(issue: Mapping, owner: str = OWNER_LOGIN) -> bool:
    author = issue.get("author")
    login = author.get("login") if isinstance(author, Mapping) else None
    return isinstance(login, str) and login.casefold() == owner.casefold()


# ---- deciding ----------------------------------------------------------------------------------------------

def _dry_copy(scope: L.Scope, into: Path) -> L.Scope:
    """A throwaway copy of the learning ledger, so a dry run exercises the real guards (and the refusal
    event a real run would write) without touching the real chain."""
    into.mkdir(parents=True, exist_ok=True)
    clone = L.Scope(scope.name, into / scope.events.name, into / scope.challenger_bets.name,
                    into / scope.lessons.name, scope.pause_file)
    for src, dst in ((scope.events, clone.events), (scope.challenger_bets, clone.challenger_bets),
                     (scope.lessons, clone.lessons)):
        if Path(src).exists():
            shutil.copyfile(src, dst)
    return clone


def _dry_card(card_paths: coach_card.Paths, into: Path) -> coach_card.Paths:
    """A throwaway copy of the report-card ledger, so a dry run records into scratch space only."""
    into.mkdir(parents=True, exist_ok=True)
    clone = coach_card.Paths(into / card_paths.ledger.name, into / card_paths.shadow.name)
    if Path(card_paths.ledger).exists():
        shutil.copyfile(card_paths.ledger, clone.ledger)
    return clone


class Decision:
    """What to do about one issue: ``outcome`` in accepted / refused / ignored / waiting, the comment, the
    label to add (None for waiting) and whether to close."""

    def __init__(self, outcome: str, comment: str, label: Optional[str], close: bool):
        self.outcome, self.comment, self.label, self.close = outcome, comment, label, close


def decide(issue: Mapping, *, scope: L.Scope, coach_on: bool, champion_ledger, now: datetime,
           owner: str = OWNER_LOGIN, tunable_cfg: Optional[Mapping] = None,
           card_paths: Optional[coach_card.Paths] = None, registry: Optional[Mapping] = None) -> Decision:
    """Judge one issue and (unless ``scope`` is a throwaway copy) record an accepted or refused proposal in
    the learning ledger. Makes no ``gh`` call. With ``card_paths`` the practice lane is on: the issue is
    recorded once in the coach report card too (``decide_card``)."""
    if not is_owner(issue, owner):
        return Decision("ignored", "ignored: not from the owner account", LABEL_REFUSED, True)
    if not coach_on:
        return Decision("waiting", "waiting: the coach switch is off (config/hounds_coach.json), so this "
                        "stays open and runs once the switch is turned on", None, False)
    if card_paths is not None:
        return decide_card(issue, scope=scope, champion_ledger=champion_ledger, now=now, tunable_cfg=tunable_cfg,
                           card_paths=card_paths, registry=registry)
    try:
        fields = parse_proposal(issue.get("body"))
    except IntakeError as exc:
        return Decision("refused", f"refused: {exc.code} {_echo(exc)}", LABEL_REFUSED, True)
    state = L.read_state(scope)
    graded = proposals.pack_graded_count(fields["hound"], state.champion_version(fields["hound"]),
                                         champion_ledger)
    try:
        c = proposals.propose_pack(scope, fields["hound"], fields["params"], fields["hypothesis"],
                                   fields["evidence"], graded=graded, coach_on=coach_on, now=now,
                                   proposed_by=PROPOSED_BY, tunable_cfg=tunable_cfg)
    except proposals.ProposalError as exc:
        if exc.code in proposals.NOT_RECORDED:
            return Decision("waiting", f"waiting: {exc.code} ({_echo(exc)}); this stays open and runs "
                            "once the owner turns the coach back on", None, False)
        return Decision("refused", f"refused: {exc.code} {_echo(exc)}", LABEL_REFUSED, True)
    return Decision("accepted", f"accepted: challenger {c.id} now runs in shadow; the referee decides",
                    LABEL_ACCEPTED, True)


# ---- the practice lane ---------------------------------------------------------------------------------------------

PRACTICE_COMMENT = ("accepted as practice: the coach report card will grade this suggestion by code, "
                    "in hindsight and live; no hound changes")


def issue_url(number: int) -> str:
    return f"https://github.com/{REPO}/issues/{number}"


def _refuse(card_paths, number, hound, code, message, *, now, created) -> Decision:
    coach_card.append(card_paths, coach_card.K_REFUSED, now=now, issue=number, issue_url=issue_url(number),
                      hound=hound[:80] if isinstance(hound, str) else None, reason=code,
                      message=_echo(message), issue_created_utc=created, proposed_by=PROPOSED_BY)
    return Decision("refused", f"refused: {code} {_echo(message)}", LABEL_REFUSED, True)


def _already_recorded(card: coach_card.Card, number: int) -> Decision:
    row = card.outcome_of(number)
    if row.get("kind") == coach_card.K_REFUSED:
        return Decision("refused", f"refused: {row.get('reason')} (already recorded by the coach report card)",
                        LABEL_REFUSED, True)
    if row.get("mode") == coach_card.MODE_CHALLENGER:
        return Decision("accepted", f"accepted: challenger {row.get('challenger_id')} now runs in shadow; "
                        "the referee decides", LABEL_ACCEPTED, True)
    return Decision("accepted", PRACTICE_COMMENT, LABEL_ACCEPTED, True)


def decide_card(issue: Mapping, *, scope: L.Scope, champion_ledger, now: datetime,
                tunable_cfg: Optional[Mapping], card_paths: coach_card.Paths,
                registry: Optional[Mapping] = None) -> Decision:
    """One owner issue, recorded once in the coach report card.

    Order: dedupe by issue number; the fence and its four fields; the hound must be tunable; the knob values
    (bounds, grid, 1 or 2 knobs); the hypothesis and evidence text; the practice rate limit. A valid
    suggestion is a practice row, and ALSO a real shadow challenger when the pre-registered guards (50 graded
    forward bets, the cooldown, the caps, the repeat checks, the pause) accept it: those guards are
    ``proposals.eligibility`` and ``propose_pack`` unchanged, so the practice lane never loosens them."""
    from src.hounds import pack as pack_mod
    number = issue["number"]
    created = issue.get("created_at") or issue.get("createdAt")
    card = coach_card.load(card_paths)
    if card.seen(number):
        return _already_recorded(card, number)
    try:
        fields = parse_proposal(issue.get("body"))
    except IntakeError as exc:
        return _refuse(card_paths, number, None, exc.code, exc, now=now, created=created)
    hound_id = fields["hound"]
    cfg = tunable_cfg if tunable_cfg is not None else tunables.load()
    reg = registry if registry is not None else pack_mod.BY_ID
    tun = cfg.get(hound_id)
    if tun is None or hound_id not in reg:
        return _refuse(card_paths, number, hound_id, "not_tunable", f"{hound_id} declares no tunable knobs",
                       now=now, created=created)
    state = L.read_state(scope)
    champ = tunables.full_values(tun, state.champion_params(hound_id))
    try:
        values = tunables.validate(tun, champ, fields["params"])
    except tunables.TunableError as exc:
        return _refuse(card_paths, number, hound_id, "params_invalid", exc, now=now, created=created)
    try:
        text = proposals.clean_text(fields["hypothesis"], "hypothesis", rules.HYPOTHESIS_MIN, rules.HYPOTHESIS_MAX)
        refs = proposals.clean_evidence(fields["evidence"])
    except proposals.ProposalError as exc:
        return _refuse(card_paths, number, hound_id, exc.code, exc, now=now, created=created)
    limited = coach_card.rate_limit_reason(card, hound_id, now)
    if limited:
        code, _, why = limited.partition(": ")
        return _refuse(card_paths, number, hound_id, code, why, now=now, created=created)

    mode, challenger_id, blocked = coach_card.MODE_PRACTICE, None, None
    version = state.champion_version(hound_id)
    graded = proposals.pack_graded_count(hound_id, version, champion_ledger)
    stop = proposals.eligibility(state, hound_id, graded=graded, now=now)
    if stop is not None:
        blocked = stop[0]
    else:
        try:
            c = proposals.propose_pack(scope, hound_id, fields["params"], text, refs, graded=graded,
                                       coach_on=True, now=now, proposed_by=PROPOSED_BY, tunable_cfg=cfg)
            mode, challenger_id = coach_card.MODE_CHALLENGER, c.id
        except proposals.ProposalError as exc:
            blocked = exc.code
    coach_card.append(
        card_paths, coach_card.K_SUGGESTION, now=now, issue=number, issue_url=issue_url(number),
        hound=hound_id, hound_name=tun.name, champion_version=version, champion_values=champ,
        suggested_values=values, changes=coach_card.change_list(tun, champ, values), hypothesis=text,
        evidence=refs, mode=mode, challenger_id=challenger_id, challenger_blocked_by=blocked,
        graded_forward_bets=graded, recorded_utc=coach_card.iso(now), issue_created_utc=created,
        proposed_by=PROPOSED_BY)
    if mode == coach_card.MODE_CHALLENGER:
        return Decision("accepted", f"accepted: challenger {challenger_id} now runs in shadow; the referee decides",
                        LABEL_ACCEPTED, True)
    return Decision("accepted", PRACTICE_COMMENT, LABEL_ACCEPTED, True)


# ---- the public issues API (read-only; runs on Actions with no token) ---------------------------------------------

API_URL = f"https://api.github.com/repos/{REPO}/issues?labels={LABEL_PROPOSAL}&state=all&per_page=50"
API_TIMEOUT_S = 20
USER_AGENT = "linehound-coach-intake (+https://linehound.app)"


def normalise_issue(raw) -> Optional[dict]:
    """One issue in the shape ``decide`` reads (``number, author.login, body, title, created_at``), from the
    REST API's shape (``user.login``) or ``gh``'s (``author.login``). A pull request, or anything without an
    integer number, is None."""
    if not isinstance(raw, Mapping) or isinstance(raw.get("number"), bool) or not isinstance(raw.get("number"), int):
        return None
    if raw.get("pull_request"):
        return None
    who = raw.get("author") if isinstance(raw.get("author"), Mapping) else raw.get("user")
    login = who.get("login") if isinstance(who, Mapping) else None
    return {"number": raw["number"], "author": {"login": login}, "body": raw.get("body"),
            "title": raw.get("title"), "created_at": raw.get("created_at") or raw.get("createdAt"),
            "state": raw.get("state"), "comments": []}


def fetch_public_issues(*, urlopen: Optional[Callable] = None, token: Optional[str] = None,
                        url: str = API_URL) -> list:
    """The coach-proposal issues from the PUBLIC GitHub REST API, oldest first. Unauthenticated works (the
    repo is public); a token, if given, is only a bearer for the rate limit. ``urlopen(request, timeout=)``
    is the test seam. Raises ``IntakeError('api_failed')`` on any transport or parse failure."""
    opener = urlopen or urllib.request.urlopen
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener(request, timeout=API_TIMEOUT_S) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise IntakeError("api_failed", f"GitHub answered {exc.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise IntakeError("api_failed", f"could not reach GitHub: {type(exc).__name__}") from None
    try:
        rows = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except ValueError:
        raise IntakeError("api_failed", "GitHub did not return JSON") from None
    if not isinstance(rows, list):
        raise IntakeError("api_failed", "GitHub did not return a list of issues")
    issues = [i for i in (normalise_issue(r) for r in rows) if i is not None]
    return sorted(issues, key=lambda i: i["number"])


def read_fixture(path) -> list:
    """Issues from a JSON file (a list in the API's or gh's shape). For tests only."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise IntakeError("api_failed", "the fixture must be a JSON list of issues")
    return sorted((i for i in (normalise_issue(r) for r in rows) if i is not None), key=lambda i: i["number"])


def run_readonly(issues: Sequence[Mapping], *, scope: L.Scope, card_paths: coach_card.Paths, coach_on: bool,
                 champion_ledger, now: datetime, owner: str = OWNER_LOGIN, tunable_cfg=None, registry=None,
                 say: Callable = print) -> dict:
    """Record every unseen owner issue in the report card. No ``gh``, no comment, no close. Returns counts."""
    counts = {"issues": len(issues), "suggested": 0, "challengers": 0, "refused": 0, "already": 0,
              "ignored": 0, "waiting": 0}
    card = coach_card.load(card_paths)
    for issue in issues:
        number = issue["number"]
        if not is_owner(issue, owner):
            counts["ignored"] += 1                # a stranger's issue on a public repo is not coaching
            continue
        if card.seen(number):
            counts["already"] += 1
            continue
        try:
            d = decide(issue, scope=scope, coach_on=coach_on, champion_ledger=champion_ledger, now=now,
                       owner=owner, tunable_cfg=tunable_cfg, card_paths=card_paths, registry=registry)
        except Exception as exc:  # noqa: BLE001 -- one issue that breaks a reader must not stop the others
            counts["errors"] = counts.get("errors", 0) + 1
            say(f"  #{number} error: {type(exc).__name__}: {_echo(exc)}")
            continue
        say(f"  #{number} {d.comment}")
        if d.outcome == "waiting":
            counts["waiting"] += 1
        elif d.outcome == "refused":
            counts["refused"] += 1
        elif d.outcome == "accepted":
            counts["suggested"] += 1
            if d.comment.startswith("accepted: challenger"):
                counts["challengers"] += 1
    return counts


# ---- the fan lane (docs/COACH_REPORT_CARD.md, "The fan lane") -----------------------------------------------------

TIPS_PATH = "/hounds/tips/export"
TIPS_TIMEOUT_S = 20
TIPS_MAX_BYTES = 5_000_000
TIPS_MAX_ROWS = 5000               # the export's own ceiling (fan_tips.EXPORT_LIMIT)
TIPS_SINCE_SLACK_S = 60            # re-read a minute before the newest recorded tip; tip ids dedupe the overlap
PROPOSED_BY_FAN = "fan"
_TIP_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_NICK_DROP = re.compile(r"[^A-Za-z0-9 ]")


def tips_base_url() -> str:
    """The site's public address, from the same setting the app's other public links read (PUBLIC_BASE_URL,
    default https://linehound.app): tests point it at a fake."""
    from src.hounds import kennel_feed
    return kennel_feed.site_base_url()


def tips_since(card: coach_card.Card) -> Optional[str]:
    """Where to resume the export: a minute before the newest tip already recorded, or None for all of it."""
    last = coach_card.parse(card.fan_last_tip_utc)
    return coach_card.iso(last - timedelta(seconds=TIPS_SINCE_SLACK_S)) if last else None


def fetch_tip_export(since: Optional[str], *, base_url: Optional[str] = None,
                     urlopen: Optional[Callable] = None) -> list:
    """The fan tips from the public export, oldest first, as raw dicts (each one re-validated by
    ``record_fan_tips``). Raises ``IntakeError('tips_failed')`` on any transport or parse failure, a 404
    included (the route exists only after the deploy that ships it)."""
    base = (base_url or tips_base_url()).rstrip("/")
    url = base + TIPS_PATH + (("?since=" + urllib.parse.quote(since, safe="")) if since else "")
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with opener(request, timeout=TIPS_TIMEOUT_S) as resp:
            raw = resp.read(TIPS_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise IntakeError("tips_failed", f"the tip export answered {exc.code} ({url})") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise IntakeError("tips_failed", f"could not reach the tip export: {type(exc).__name__}") from None
    if len(raw) > TIPS_MAX_BYTES:
        raise IntakeError("tips_failed", "the tip export is larger than expected; not read")
    try:
        body = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except ValueError:
        raise IntakeError("tips_failed", "the tip export did not return JSON") from None
    rows = body.get("tips") if isinstance(body, Mapping) else None
    if not isinstance(rows, list):
        raise IntakeError("tips_failed", "the tip export has no list of tips")
    return rows[:TIPS_MAX_ROWS]


def clean_nickname(raw) -> Optional[str]:
    """A fan's nickname made safe for a public page, or None. Intake never trusts the export: anything the
    tip box would refuse is dropped here too (characters first, then the site's own text rules)."""
    if not isinstance(raw, str):
        return None
    text = " ".join(_NICK_DROP.sub(" ", raw).split())[:20].strip()
    if not text:
        return None
    from src.hounds import fan_tips
    try:
        return fan_tips.clean_nickname(text)
    except fan_tips.TipError:
        return None


def _one_tip(raw) -> Optional[dict]:
    """The fields intake reads from one export row, or None when it is not a tip."""
    if not isinstance(raw, Mapping):
        return None
    tip_id, hound = raw.get("id"), raw.get("hound_id")
    made = coach_card.parse(raw.get("created_utc"))
    if not isinstance(tip_id, str) or not _TIP_ID.match(tip_id) or not isinstance(hound, str) \
            or not hound.strip() or len(hound) > 80 or made is None or not isinstance(raw.get("values"), Mapping):
        return None
    return {"id": tip_id, "hound": hound.strip(), "values": raw["values"], "nickname": raw.get("nickname"),
            "created": made}


def _tip_order(raw) -> tuple:
    if isinstance(raw, Mapping):
        return (str(raw.get("created_utc")), str(raw.get("id")))
    return ("", "")


def record_fan_tips(rows: Sequence, *, scope: L.Scope, card_paths: coach_card.Paths, now: datetime,
                    tunable_cfg: Optional[Mapping] = None, registry: Optional[Mapping] = None,
                    say: Callable = print) -> dict:
    """Record the unseen fan tips in the report card's fan lane. Returns counts.

    Per tip, oldest first: a malformed row is dropped; a tip id already recorded (as a row or as a repeat) is
    skipped; the hound must declare tunable knobs; the values meet ``tunables.validate`` against the hound's
    CURRENT champion (bounds, grid, 1 or 2 knobs changed) or the tip is refused; a repeat of the day's tip (same
    hound, same values, same UTC day the fan sent it) adds one to the first row's count; a day that already holds
    ``FAN_PER_UTC_DAY`` rows takes no more. A tip is never offered to ``propose_pack``, so a fan can never cause
    a challenger: the row's mode is ``fan`` and its challenger fields are empty. Refused and over-the-cap tips
    are counted here but not written, so a ledger cannot be filled by bad input."""
    from src.hounds import pack as pack_mod
    cfg = tunable_cfg if tunable_cfg is not None else tunables.load()
    reg = registry if registry is not None else pack_mod.BY_ID
    counts = {"read": len(rows), "recorded": 0, "collapsed": 0, "already": 0, "invalid": 0, "not_tunable": 0,
              "over_cap": 0, "malformed": 0}
    card = coach_card.load(card_paths)
    state = None
    for raw in sorted(rows, key=_tip_order):
        tip = _one_tip(raw)
        if tip is None:
            counts["malformed"] += 1
            continue
        if tip["id"] in card.fan_tip_ids:
            counts["already"] += 1
            continue
        tun = cfg.get(tip["hound"])
        if tun is None or tip["hound"] not in reg:
            counts["not_tunable"] += 1
            continue
        if state is None:
            state = L.read_state(scope)
        champ = tunables.full_values(tun, state.champion_params(tip["hound"]))
        try:
            values = tunables.validate(tun, champ, tip["values"])
        except (tunables.TunableError, ValueError, OverflowError, TypeError) as exc:
            # ValueError/OverflowError: a NaN or Infinity in the export (json.loads accepts both) breaks the grid
            # check inside tunables.validate; it is an invalid tip like any other, not a crash of the run
            counts["invalid"] += 1
            say(f"  tip {tip['id']} refused: {_echo(exc)}")
            continue
        day = coach_card.iso(tip["created"])[:10]
        first = coach_card.fan_duplicate_of(card, tip["hound"], values, day)
        if first is not None:
            coach_card.append(card_paths, coach_card.K_FAN_COUNT, now=now, issue=first, tip_id=tip["id"],
                              hound=tip["hound"], tip_created_utc=coach_card.iso(tip["created"]))
            counts["collapsed"] += 1
            card = coach_card.load(card_paths)
            continue
        if coach_card.fan_day_full(card, day):
            counts["over_cap"] += 1
            continue
        coach_card.append(
            card_paths, coach_card.K_FAN_TIP, now=now, issue=coach_card.next_fan_key(card), tip_id=tip["id"],
            hound=tip["hound"], hound_name=tun.name, champion_version=state.champion_version(tip["hound"]),
            champion_values=champ, suggested_values=values, changes=coach_card.change_list(tun, champ, values),
            mode=coach_card.MODE_FAN, challenger_id=None, nickname=clean_nickname(tip.get("nickname")),
            tip_created_utc=coach_card.iso(tip["created"]), recorded_utc=coach_card.iso(now),
            proposed_by=PROPOSED_BY_FAN)
        counts["recorded"] += 1
        card = coach_card.load(card_paths)
    return counts


# ---- the run -------------------------------------------------------------------------------------------------

def _already_said(issue: Mapping, comment: str) -> bool:
    """A 'waiting' comment is posted once: a run every day must not add one a day."""
    for existing in issue.get("comments") or []:
        body = existing.get("body") if isinstance(existing, Mapping) else None
        if isinstance(body, str) and body.strip() == comment.strip():
            return True
    return False


def list_issues(runner: Runner, repo: str) -> list:
    code, out, err = runner(["issue", "list", "--repo", repo, "--label", LABEL_PROPOSAL, "--state", "open",
                             "--json", "number,author,body,title,comments", "--limit", str(MAX_ISSUES)])
    if code != 0:
        raise IntakeError("gh_failed", f"gh issue list failed: {_echo(err or out)}")
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        raise IntakeError("gh_failed", "gh issue list did not return JSON") from None
    return sorted((r for r in rows if isinstance(r, dict) and isinstance(r.get("number"), int)),
                  key=lambda r: r["number"])


def _write(runner: Runner, args: Sequence[str], problems: list) -> None:
    code, out, err = runner(args)
    if code != 0:
        problems.append(f"gh {' '.join(args[:2])} failed: {_echo(err or out)}")


def run(*, runner: Runner, repo: str = REPO, dry_run: bool = False, scope: Optional[L.Scope] = None,
        coach_on: Optional[bool] = None, champion_ledger=None, now: Optional[datetime] = None,
        owner: str = OWNER_LOGIN, tunable_cfg: Optional[Mapping] = None, say: Callable = print,
        card_paths: Optional[coach_card.Paths] = None) -> int:
    """Process every open ``coach-proposal`` issue. Returns 0, or 1 if ``gh`` could not read the issues or
    a write failed (the decisions already recorded in the ledger stand)."""
    scope = scope or L.Scope.house()
    now = now or L.utc_now()
    on = coach_brief.coach_switch_on() if coach_on is None else coach_on
    if champion_ledger is None:
        from src.hounds import pack_run
        champion_ledger = pack_run.ledger_path()
    try:
        issues = list_issues(runner, repo)
    except IntakeError as exc:
        say(f"coach intake: {exc}")
        return 1
    say(f"coach intake: {len(issues)} open {LABEL_PROPOSAL} issue(s)"
        + (" [dry run]" if dry_run else "") + ("" if on else " [coach switch is off]"))
    if not issues:
        return 0

    problems: list = []
    with tempfile.TemporaryDirectory() as scratch:
        work = _dry_copy(scope, Path(scratch)) if dry_run else scope
        work_card = _dry_card(card_paths, Path(scratch)) if (dry_run and card_paths) else card_paths
        labels_ready = dry_run
        for issue in issues:
            number = issue["number"]
            d = decide(issue, scope=work, coach_on=on, champion_ledger=champion_ledger, now=now,
                       owner=owner, tunable_cfg=tunable_cfg, card_paths=work_card)
            say(f"  #{number} {d.comment}")
            if dry_run:
                continue
            if d.outcome == "waiting" and _already_said(issue, d.comment):
                continue
            if d.label and not labels_ready:
                for name, (color, desc) in LABELS.items():       # best effort: an existing label is fine
                    runner(["label", "create", name, "--repo", repo, "--color", color,
                            "--description", desc])
                labels_ready = True
            _write(runner, ["issue", "comment", str(number), "--repo", repo, "--body", d.comment], problems)
            if d.label:
                _write(runner, ["issue", "edit", str(number), "--repo", repo, "--add-label", d.label],
                       problems)
            if d.close:
                _write(runner, ["issue", "close", str(number), "--repo", repo], problems)
    for p in problems:
        say(f"  problem: {p}")
    return 1 if problems else 0


SOURCES = ("gh", "api", "fixture", "tips")


def parse_sources(text: str) -> tuple:
    """``api,tips`` as ``("api", "tips")``. ``gh`` writes to GitHub and runs alone."""
    found = tuple(dict.fromkeys(p.strip() for p in str(text).split(",") if p.strip()))
    if not found or any(p not in SOURCES for p in found):
        raise argparse.ArgumentTypeError(f"--source takes {', '.join(SOURCES)} (api, fixture and tips can be "
                                         "combined with commas)")
    if "gh" in found and len(found) > 1:
        raise argparse.ArgumentTypeError("--source gh runs alone")
    return found


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.coach_intake",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--source", type=parse_sources, default=("gh",), metavar="SOURCE[,SOURCE]",
                    help="gh = open issues through the gh CLI, then comment/label/close (local only); "
                         "api = the public GitHub REST API, read-only (runs on Actions); "
                         "fixture = a JSON file (tests only); "
                         "tips = the fans' tips from the site's public export (the fan lane). "
                         "api, fixture and tips can be combined: --source api,tips")
    ap.add_argument("--file", help="the issues file for --source fixture")
    ap.add_argument("--grade", action="store_true",
                    help="after intake, grade the coach's suggestions (hindsight and the live shadow comparison)")
    ap.add_argument("--time-budget-s", type=float, default=100.0, help="stop starting grading stages after this")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would happen; no gh writes, no ledger writes")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--base-url", help="the site address for --source tips (default: PUBLIC_BASE_URL, else "
                                       "https://linehound.app)")
    ap.add_argument("--root", help="house scope and report-card directory (testing seam)")
    ap.add_argument("--champion-ledger", help="the pack ledger (testing seam)")
    ap.add_argument("--coach-config", help="the kill-switch file (testing seam)")
    ap.add_argument("--now", help="the clock, ISO UTC (testing seam)")
    return ap


def run_source(issues: Optional[Sequence[Mapping]], *, scope: L.Scope, card_paths: coach_card.Paths,
               coach_on: bool, champion_ledger, now: datetime, dry_run: bool, grade: bool, time_budget_s: float,
               tunable_cfg=None, registry=None, loader=None, say: Callable = print,
               tips: Optional[Sequence] = None) -> int:
    """The read-only path (api, fixture, tips): record unseen owner issues (``issues``, None when that source
    was not asked for) and the fans' tips (``tips``, None likewise), then optionally grade everything."""
    import time
    if issues is not None:
        say(f"coach intake: {len(issues)} {LABEL_PROPOSAL} issue(s) read"
            + (" [dry run]" if dry_run else "") + ("" if coach_on else " [coach switch is off]"))
    elif tips is not None:
        say(f"coach intake: {len(tips)} fan tip(s) read" + (" [dry run]" if dry_run else ""))
    with tempfile.TemporaryDirectory() as scratch:
        work = _dry_copy(scope, Path(scratch)) if dry_run else scope
        work_card = _dry_card(card_paths, Path(scratch)) if dry_run else card_paths
        if issues is not None:
            counts = run_readonly(issues, scope=work, card_paths=work_card, coach_on=coach_on,
                                  champion_ledger=champion_ledger, now=now, tunable_cfg=tunable_cfg,
                                  registry=registry, say=say)
            say("  " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        if tips is not None:
            if issues is not None:
                say(f"coach intake: {len(tips)} fan tip(s) read")
            fan_counts = record_fan_tips(tips, scope=work, card_paths=work_card, now=now,
                                         tunable_cfg=tunable_cfg, registry=registry, say=say)
            say("  fans: " + ", ".join(f"{k} {v}" for k, v in fan_counts.items()))
        if grade:
            if dry_run:
                card = coach_card.load(work_card)
                n = len(card.suggestions)
                extra = f" and {len(card.fans)} fan tip(s)" if card.fans else ""
                say(f"  grading skipped in a dry run ({n} suggestion(s){extra} would be graded)")
            else:
                from src.hounds import coach_grade
                done = coach_grade.grade_all(work_card, now=now, deadline=time.monotonic() + time_budget_s,
                                             tun_cfg=tunable_cfg, registry=registry, loader=loader, say=say)
                say("  graded: " + ", ".join(f"{k} {v}" for k, v in done.items()))
    return 0


def main(argv: Optional[Sequence[str]] = None, *, runner: Optional[Runner] = None,
         urlopen: Optional[Callable] = None) -> int:
    args = build_parser().parse_args(argv)
    sources = args.source
    root = Path(args.root) if args.root else None
    scope = L.Scope.house(root)
    card_paths = coach_card.Paths.default(root)
    on = coach_brief.coach_switch_on(Path(args.coach_config) if args.coach_config else None)
    now = L.parse(args.now) if args.now else None
    if sources == ("gh",):
        return run(runner=runner or default_runner, repo=args.repo, dry_run=args.dry_run, scope=scope,
                   coach_on=on, champion_ledger=args.champion_ledger, now=now, card_paths=card_paths)
    champion_ledger = args.champion_ledger
    if champion_ledger is None:
        from src.hounds import pack_run
        champion_ledger = pack_run.ledger_path()
    issues, tips, failed = None, None, 0
    # Each source fails alone: an unreachable GitHub must not cost the fans their grading, and a site that has
    # not shipped the export yet (a 404) must not cost the coach's. Only when nothing at all could be read does
    # the run stop before grading, as the single-source run always has.
    if "api" in sources or "fixture" in sources:
        try:
            if "api" in sources:
                token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip() or None
                issues = fetch_public_issues(urlopen=urlopen, token=token)
            else:
                if not args.file:
                    print("coach intake: --source fixture needs --file")
                    return 2
                issues = read_fixture(args.file)
        except (IntakeError, OSError, ValueError) as exc:
            print(f"coach intake: {exc}")
            failed += 1
    if "tips" in sources:
        try:
            tips = fetch_tip_export(tips_since(coach_card.load(card_paths)), base_url=args.base_url,
                                    urlopen=urlopen)
        except (IntakeError, OSError, ValueError) as exc:
            print(f"coach intake: fan tips: {exc}")
            failed += 1
    if issues is None and tips is None:
        return 1
    code = run_source(issues, scope=scope, card_paths=card_paths, coach_on=on, champion_ledger=champion_ledger,
                      now=now or L.utc_now(), dry_run=args.dry_run, grade=args.grade,
                      time_budget_s=args.time_budget_s, tips=tips)
    return 1 if failed else code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
