"""LineHound Hounds: a public, paper-only race of betting strategies.

A *hound* is a named rule that makes simulated flat one-unit bets, written
down before the game, graded afterwards, and refereed against the closing
price instead of against its own luck. Nothing here places, sizes or routes a
real bet, and nothing here claims an edge: see ``docs/HOUNDS.md`` and the
referee's pre-registration, ``docs/PREREG_HOUND_VERDICT.md``.

Module map (who owns what):

  contract   the JSON shapes every route returns (shared by the web pages,
             house hounds and user hounds)
  verdict    the pre-registered referee: labels, bootstrap, retirement
  ledgers    readers that turn each source of bets into one normalised shape
  boards     one streaming pass over the captured odds: average price,
             "verified", and the closing boards for CLV
  stats      the numbers per hound, cached on file size + mtime
  house      the house pack: metadata from config/house_hounds.json and
             config/house_pack.json

``src/hounds/user_*.py`` (user-built hounds) and ``src/hounds/pack/*``
(the strategy pack) belong to other workers and are only READ here, through
their ledgers.
"""

PAPER_ONLY = True

NOT_ADVICE = ("Paper only, not advice. Every hound makes simulated one-unit "
              "bets; no money is staked and nothing here tells anyone what "
              "to bet.")
