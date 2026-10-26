"""The Learner: a house hound that starts with no rules, bets small and wide on paper, and keeps the evidence.

It is "the Apprentice seeded by the market instead of one human" (``src/hounds/apprentice``): the Apprentice learns from its
owner's real bets; the Learner learns from its own settled paper bets. Same discipline: nothing it learns is applied until a
person has read it, and every pattern is shown with its sample size, never as a promise.

  features   what is frozen onto each bet at placement: ~28 point-in-time facts, all read from data observed before the lock
  state      the append-only record of what it proposed, what the owner applied and what the owner vetoed
  learn      phase 2: fit on settled bets before a cutoff, test forward on the next week, write a PROPOSAL (never an apply)

The hound itself is the thin adapter ``src/hounds/pack/learner_hound.py``. It shares the AI hounds' config file, ledger, sports
gate and runner (``config/ai_hounds.json``, family ``learner``) and asks no model: no key, no network, no cost. Its bets are
graded by ``pack_settle`` like every other hound's, at the board-average price.

Paper only. Forward only. No edge or profit is claimed: with the book's cut, most patterns found this way are noise, and the
public record is the only evidence of whether it learns.
"""

HOUND_ID = "learner"
CATEGORY = "learner"
FAMILY = "learner"
EXPERIMENTAL_LINE = ("Starts with no rules. Bets small and wide on paper, then shows what held up. "
                     "Graded in public like every hound; the record shows whether it learns, never a promise.")
HONESTY = ("A proposal is a hypothesis from settled paper bets and one week of results it had not seen. With the book's cut, most "
           "patterns found this way are luck. Nothing changes until the owner applies it, and every bet stays paper only.")
NOT_ENOUGH = "Not enough settled bets to learn yet."
