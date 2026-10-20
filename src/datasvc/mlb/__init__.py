"""MLB through the data service's door, by WRAPPING what LineHound already has.

There is no MLB ingest here and none is planned: the results, pitcher, bullpen, lineup, standings
and odds stores are filled by the existing capture and refresh jobs, and the analyst's frozen evidence
packet (`src/analyst/packet.py`) is built by the existing analyst code. This package gives those one
more entry (`/data/v1/mlb/...` and `DataClient`) with the same envelope as UFC and NFL: stable ids,
source identity, observation time, coverage, missing reasons and a `data_version`.

  service.py   `MlbService`: the schedule and results, the matchup packet, quotes, pitcher history
               and `/status` datasets, each cached against the version of the stores it was built from

MLB keeps its own shapes. Nothing here forces a game, a fixture or a packet into the UFC or NFL form.

ONE INGEST EXISTS, added 2026-10-20: the statsapi box-score layer (forward only, sealed window enforced in code).

  seal.py         the sealed window 2026-01-01..2026-08-27, the forward floor, and the URL guard
  statsapi.py     parsers, `MlbBoxStore`, `refresh` (schedule per day + box score per finished game), check
  box_service.py  `MlbBoxService`: schedule, game, histories, season averages and splits (ESPN-layer reads)
  box_cli.py      `python -m src.cli datasvc mlbbox ...`
"""
