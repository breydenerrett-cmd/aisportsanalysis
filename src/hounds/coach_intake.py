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

WHERE IT RUNS. Not in the capture slot: every workflow's GITHUB_TOKEN has contents (and actions) permission
only, no ``issues``, so a runner could not comment, label or close. It runs where ``gh`` is signed in as the
owner (docs/ZAPS.md). It reads and writes the same ledger as the capture slots, so pull before and push right
after: a rejected push loses the proposal while its issue is already closed.
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
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from src.hounds.learning import coach_brief, proposals
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


class Decision:
    """What to do about one issue: ``outcome`` in accepted / refused / ignored / waiting, the comment, the
    label to add (None for waiting) and whether to close."""

    def __init__(self, outcome: str, comment: str, label: Optional[str], close: bool):
        self.outcome, self.comment, self.label, self.close = outcome, comment, label, close


def decide(issue: Mapping, *, scope: L.Scope, coach_on: bool, champion_ledger, now: datetime,
           owner: str = OWNER_LOGIN, tunable_cfg: Optional[Mapping] = None) -> Decision:
    """Judge one issue and (unless ``scope`` is a throwaway copy) record an accepted or refused proposal in
    the learning ledger. Makes no ``gh`` call."""
    if not is_owner(issue, owner):
        return Decision("ignored", "ignored: not from the owner account", LABEL_REFUSED, True)
    if not coach_on:
        return Decision("waiting", "waiting: the coach switch is off (config/hounds_coach.json), so this "
                        "stays open and runs once the switch is turned on", None, False)
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
        owner: str = OWNER_LOGIN, tunable_cfg: Optional[Mapping] = None, say: Callable = print) -> int:
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
        labels_ready = dry_run
        for issue in issues:
            number = issue["number"]
            d = decide(issue, scope=work, coach_on=on, champion_ledger=champion_ledger, now=now,
                       owner=owner, tunable_cfg=tunable_cfg)
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m src.hounds.coach_intake",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would happen; no gh writes, no ledger writes")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--root", help="house scope directory (testing seam)")
    ap.add_argument("--champion-ledger", help="the pack ledger (testing seam)")
    ap.add_argument("--coach-config", help="the kill-switch file (testing seam)")
    ap.add_argument("--now", help="the clock, ISO UTC (testing seam)")
    return ap


def main(argv: Optional[Sequence[str]] = None, *, runner: Optional[Runner] = None) -> int:
    args = build_parser().parse_args(argv)
    scope = L.Scope.house(Path(args.root) if args.root else None)
    return run(runner=runner or default_runner, repo=args.repo, dry_run=args.dry_run, scope=scope,
               coach_on=coach_brief.coach_switch_on(Path(args.coach_config) if args.coach_config else None),
               champion_ledger=args.champion_ledger, now=L.parse(args.now) if args.now else None)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
