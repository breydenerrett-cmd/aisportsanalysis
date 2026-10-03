"""The situation layer: the bigger picture around a matchup.

`docs/SITUATION_LAYER_PLAN.md` is the plan and `docs/SITUATION_LAYER.md` says what was
built. The package is stdlib only and pure: every function takes what it reads as an
argument (a results list, a UFC store) and reads nothing else, so the same inputs give
the same record in any order, and a test needs no disk and no network.

    record.py            the one record shape: factors, gaps, the packet section, the page lines
    series.py            postseason series rebuilt from game results (shared by the builder
                         and the historical test)
    mlb.py               `situation_for_game`: rest and rhythm, form, stakes, pressure history,
                         head-to-head, availability, venue
    ufc.py               `situation_for_bout`: layoff, streak and finishes, title and card slot,
                         weight class, previous meeting, opponent quality trend
    postseason_history.py  display-only store of earlier postseasons from MLB's free feed
    rest_vs_rhythm.py    the first factor test: bye team against the team that played the round
                         before, in the Division Series

EVERY FACTOR IS A FACT WITH A SOURCE AND A SAMPLE, OR IT IS LISTED AS MISSING. Nothing is
guessed and no factor is trusted until it has been measured: the analyst reads these next to
the statistics (arm B of the side-by-side test) and the record says, by sport and market
family, whether that helped.
"""

from src.situation.record import VERSION  # noqa: F401
