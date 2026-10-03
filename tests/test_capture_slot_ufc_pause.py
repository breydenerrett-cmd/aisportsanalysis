"""scripts/capture_slot.sh stops publishing the UFC favourites card after the
cut-off date (owner decision 2026-10-03), and nothing else changes.

HOW THIS RUNS THE REAL SCRIPT
-----------------------------
The UFC step is lifted out of the committed script by its own markers and run
under bash, in a temp directory that is a tiny copy of the repository: the real
helper (src/appstate/ufc_public_card.py), the real src/paths.py it anchors on,
and a config file this test writes. The one stub is `python3`, a shell function:
a call to the helper runs the real Python, and any other call (the publish) just
prints what it was asked to run, so nothing is published and nothing touches the
network or a ledger. Because the helper finds config/ relative to its own
location, a temp copy with no config/ is a real "config is missing", with no
file of the repository's removed or renamed.

WHAT IS PINNED
--------------
  * before, on and after the cut-off date, against the committed config and
    against configs with other dates (the script follows the config);
  * a missing, malformed or nonsensical config keeps publishing for the dates on
    or before 2026-10-03 and keeps later dates paused (it fails closed after
    the owner's date, open on and before it);
  * the helper crashing, printing junk, or printing a Windows line ending does
    not crash the slot and does not move the date;
  * `ufc capture` (odds capture) is not behind the gate, and the publish command
    appears once, only in the publishing branch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_chain_multi_sport import BASH, _code

ROOT = Path(__file__).resolve().parent.parent
SLOT = ROOT / "scripts" / "capture_slot.sh"
CONFIG = ROOT / "config" / "ufc_public_card.json"

HELPER_FILES = ("src/__init__.py", "src/paths.py", "src/appstate/__init__.py",
                "src/appstate/ufc_public_card.py")

GATE_START = "UFC_PUBLIC_LAST_DATE=$(python3 -m src.appstate.ufc_public_card)"
PUBLISH_ECHO = 'echo "== ufc card publish ($SLATE_DATE) =="'

# `python3` as a shell function. The helper runs for real (HELPER_MODE=real) or
# is replaced by one of the ways it could misbehave; the publish only prints.
STUB = r"""
python3() {
    if [ "${1:-}" = "-m" ] && [ "${2:-}" = "src.appstate.ufc_public_card" ]; then
        case "${HELPER_MODE:-real}" in
            real)  "$PYBIN" "$@" ;;
            cr)    printf '2026-10-10\r' ;;
            junk)  echo 'not a date at all' ;;
            crash) echo 'Traceback: simulated failure'; return 3 ;;
        esac
        return $?
    fi
    echo "STUB-PUBLISH-CALLED: $*"
}
"""


def the_ufc_step(text: str) -> str:
    """The script's UFC step: from the gate's first line to the `fi` that closes
    it, comments included (they are harmless to bash)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(GATE_START))
    publish = next(i for i in range(start, len(lines)) if PUBLISH_ECHO in lines[i])
    end = next(i for i in range(publish, len(lines)) if lines[i].strip() == "fi")
    return "\n".join(lines[start:end + 1])


def published(date: str) -> list:
    return [f"== ufc card publish ({date}) ==",
            f"  STUB-PUBLISH-CALLED: -m src.cli card publish --sport mma --date {date}"]


def paused(last: str) -> list:
    return [f"== ufc card publish: paused after {last} (config/ufc_public_card.json) =="]


class _StepCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BASH:
            raise unittest.SkipTest("no POSIX bash available")
        cls.step = the_ufc_step(SLOT.read_text(encoding="utf-8"))

    def make_repo(self, config=None) -> Path:
        """A temp directory laid out like the repository, as far as the helper
        can tell: its own file, src/paths.py, and (when given) a config."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        for rel in HELPER_FILES:
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dst)
        if config is not None:
            (repo / "config").mkdir()
            (repo / "config" / "ufc_public_card.json").write_text(config, encoding="utf-8")
        return repo

    def run_dates(self, repo, dates, *, mode="real", strict=False):
        """Run the step once per date inside ONE bash and return
        ({date: its stdout lines}, stderr, return code)."""
        loop = "".join(
            f'echo "## {d}"\nSLATE_DATE={d}\n{self.step}\n' for d in dates)
        script = ("set -euo pipefail\n" if strict else "set -uo pipefail\n") \
            + STUB + loop + "echo '## STEP_SURVIVED'\n"
        env = dict(os.environ, PYBIN=sys.executable, HELPER_MODE=mode,
                   PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([BASH, "-c", script], cwd=str(repo), capture_output=True,
                              text=True, timeout=120, env=env)
        by_date, current = {}, None
        for line in done.stdout.splitlines():
            line = line.rstrip("\r")
            if line.startswith("## "):
                current = line[3:]
                by_date[current] = []
            elif current is not None:
                by_date[current].append(line)
        self.assertIn("STEP_SURVIVED", by_date, done.stdout + done.stderr)
        by_date.pop("STEP_SURVIVED")
        return by_date, done.stderr, done.returncode

    def assert_outcomes(self, got, expected):
        self.assertEqual(set(got), set(expected))
        for date, want in expected.items():
            with self.subTest(slate_date=date):
                self.assertEqual(got[date], want)


class TheStepIsFoundInTheScript(unittest.TestCase):
    def test_it_is_there_and_has_both_branches(self):
        step = the_ufc_step(SLOT.read_text(encoding="utf-8"))
        self.assertIn("src.appstate.ufc_public_card", step)
        self.assertIn("python3 -m src.cli card publish --sport mma", step)
        self.assertIn("paused after $UFC_PUBLIC_LAST_DATE (config/ufc_public_card.json)", step)
        self.assertIn("\nelse\n", step)


class AgainstTheCommittedConfig(_StepCase):
    """The config the owner's decision shipped with: 2026-10-03."""

    def test_before_on_and_after_the_cut_off(self):
        repo = self.make_repo(CONFIG.read_text(encoding="utf-8"))
        dates = ["2026-09-26", "2026-10-02", "2026-10-03",
                 "2026-10-04", "2026-10-10", "2026-11-01", "2027-01-01"]
        got, stderr, code = self.run_dates(repo, dates)
        self.assertEqual(code, 0, stderr)
        expected = {d: published(d) for d in dates[:3]}
        expected.update({d: paused("2026-10-03") for d in dates[3:]})
        self.assert_outcomes(got, expected)
        self.assertNotIn("UFC pause config", stderr, "a good config logs no warning")

    def test_a_paused_slot_prints_exactly_one_line_and_publishes_nothing(self):
        repo = self.make_repo(CONFIG.read_text(encoding="utf-8"))
        got, _stderr, _code = self.run_dates(repo, ["2026-10-10"])
        self.assertEqual(got["2026-10-10"],
                         ["== ufc card publish: paused after 2026-10-03 "
                          "(config/ufc_public_card.json) =="])
        self.assertFalse(any("STUB-PUBLISH-CALLED" in l for l in got["2026-10-10"]))


class TheScriptFollowsTheConfig(_StepCase):
    def test_a_later_date_in_the_config_publishes_up_to_that_date(self):
        repo = self.make_repo('{"favourites_rule_last_public_date": "2026-10-10"}')
        got, stderr, _ = self.run_dates(repo, ["2026-10-03", "2026-10-04", "2026-10-10",
                                               "2026-10-11"])
        self.assert_outcomes(got, {
            "2026-10-03": published("2026-10-03"),
            "2026-10-04": published("2026-10-04"),
            "2026-10-10": published("2026-10-10"),
            "2026-10-11": paused("2026-10-10"),
        })
        self.assertNotIn("UFC pause config", stderr)

    def test_an_earlier_date_in_the_config_pauses_from_that_date(self):
        repo = self.make_repo('{"favourites_rule_last_public_date": "2026-09-26"}')
        got, _stderr, _ = self.run_dates(repo, ["2026-09-26", "2026-09-27", "2026-10-03"])
        self.assert_outcomes(got, {
            "2026-09-26": published("2026-09-26"),
            "2026-09-27": paused("2026-09-26"),
            "2026-10-03": paused("2026-09-26"),
        })

    def test_a_config_with_a_byte_order_mark_is_read(self):
        repo = self.make_repo()
        (repo / "config").mkdir()
        (repo / "config" / "ufc_public_card.json").write_bytes(
            b'\xef\xbb\xbf{"favourites_rule_last_public_date": "2026-10-10"}')
        got, _stderr, _ = self.run_dates(repo, ["2026-10-10", "2026-10-11"])
        self.assert_outcomes(got, {"2026-10-10": published("2026-10-10"),
                                   "2026-10-11": paused("2026-10-10")})


class AnUnreadableConfigFailsOpenOnAndBeforeTheDateAndClosedAfter(_StepCase):
    """The deployed image did not copy config/, and a hand-edited file can be
    broken. Neither may turn the favourites back on for a later date, and
    neither may stop tonight's card."""

    DATES = ["2026-10-02", "2026-10-03", "2026-10-04", "2026-10-10"]

    def check(self, repo, problem):
        got, stderr, code = self.run_dates(repo, self.DATES)
        self.assertEqual(code, 0, stderr)
        self.assert_outcomes(got, {
            "2026-10-02": published("2026-10-02"),
            "2026-10-03": published("2026-10-03"),
            "2026-10-04": paused("2026-10-03"),
            "2026-10-10": paused("2026-10-03"),
        })
        self.assertIn(problem, stderr, "the slot log says why the built-in date was used")

    def test_no_config_directory_at_all(self):
        self.check(self.make_repo(), "could not be read")

    def test_a_config_that_is_not_json(self):
        self.check(self.make_repo("{ this is not json"), "could not be read")

    def test_a_config_with_no_date_in_it(self):
        self.check(self.make_repo('{"decided": "2026-10-03"}'), "no valid")

    def test_a_config_with_a_date_that_is_not_a_date(self):
        self.check(self.make_repo('{"favourites_rule_last_public_date": "soon"}'), "no valid")

    def test_a_config_holding_a_list(self):
        self.check(self.make_repo("[]"), "not a JSON object")


class TheHelperItselfMisbehaving(_StepCase):
    """If even the helper cannot give a date, the script's own literal does, and
    the slot is unharmed. Run under `set -euo pipefail`, stricter than the
    script's own `set -uo pipefail`."""

    def test_a_crashing_helper_does_not_fail_the_slot_or_move_the_date(self):
        got, _stderr, code = self.run_dates(self.make_repo(), ["2026-10-03", "2026-10-04"],
                                            mode="crash", strict=True)
        self.assertEqual(code, 0)
        self.assert_outcomes(got, {"2026-10-03": published("2026-10-03"),
                                   "2026-10-04": paused("2026-10-03")})

    def test_a_helper_printing_junk_is_not_a_date(self):
        got, _stderr, code = self.run_dates(self.make_repo(), ["2026-10-03", "2026-10-04"],
                                            mode="junk", strict=True)
        self.assertEqual(code, 0)
        self.assert_outcomes(got, {"2026-10-03": published("2026-10-03"),
                                   "2026-10-04": paused("2026-10-03")})

    def test_a_carriage_return_left_on_the_date_does_not_move_it(self):
        """A Windows Python prints the date with a CRLF, and a shell that does
        not drop the CR for you (any Linux bash given a Windows python.exe) is
        left with "2026-10-10\\r". Left on, it would read as junk and fall back
        to 2026-10-03, and 2026-10-10 would wrongly pause. The stub prints a lone
        trailing CR so the test means the same under Git Bash, which does strip
        the CR of a CRLF pair on its own."""
        got, _stderr, _ = self.run_dates(self.make_repo(), ["2026-10-10", "2026-10-11"],
                                         mode="cr")
        self.assert_outcomes(got, {"2026-10-10": published("2026-10-10"),
                                   "2026-10-11": paused("2026-10-10")})


class OnlyTheUfcPublishIsGated(unittest.TestCase):
    def setUp(self):
        self.text = SLOT.read_text(encoding="utf-8")
        self.code = _code(self.text)

    def test_ufc_capture_is_unchanged_and_runs_before_the_gate(self):
        line = "python3 -m src.cli ufc capture 2>&1 | sed 's/^/  /' || true"
        self.assertEqual(self.code.count(line), 1)
        self.assertLess(self.code.index(line), self.code.index(GATE_START))
        self.assertIn('echo "== ufc capture =="', self.code)

    def test_the_publish_command_appears_once_and_only_in_the_publishing_branch(self):
        publish = "python3 -m src.cli card publish --sport mma --date \"$SLATE_DATE\""
        self.assertEqual(self.code.count(publish), 1)
        step = the_ufc_step(self.text)
        then_branch, _, else_branch = step.partition("\nelse\n")
        self.assertNotIn("src.cli", then_branch, "the paused branch runs no command")
        self.assertIn(publish, else_branch)
        self.assertIn(PUBLISH_ECHO, else_branch)

    def test_the_gate_sits_between_the_nfl_publish_and_staging(self):
        gate = self.code.index(GATE_START)
        self.assertLess(self.code.index("nfl card publish"), gate)
        self.assertLess(gate, self.code.index("STAGE_PATHS="))

    def test_nothing_else_publishes_a_ufc_card(self):
        for rel in ("scripts/forward_capture.sh", "scripts/daily_loop.sh",
                    "scripts/afternoon_slate.sh", "scripts/daily_bootstrap.sh"):
            with self.subTest(script=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertNotIn("card publish --sport mma", text)

    def test_the_gate_never_exits_the_slot(self):
        step = _code(the_ufc_step(self.text))
        self.assertNotIn("exit", step)
        self.assertNotIn("ESCALATE", step)


if __name__ == "__main__":
    unittest.main()
