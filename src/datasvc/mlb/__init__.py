"""MLB through the data service's door, by WRAPPING what LineHound already has.

There is no MLB ingest here and none is planned: the results, pitcher, bullpen, lineup, standings
and odds stores are filled by the existing capture and refresh jobs, and the analyst's frozen evidence
packet (`src/analyst/packet.py`) is built by the existing analyst code. This package gives those one
more entry (`/data/v1/mlb/...` and `DataClient`) with the same envelope as UFC and NFL: stable ids,
source identity, observation time, coverage, missing reasons and a `data_version`.

  service.py   `MlbService`: the schedule and results, the matchup packet, quotes, pitcher history
               and `/status` datasets, each cached against the version of the stores it was built from

MLB keeps its own shapes. Nothing here forces a game, a fixture or a packet into the UFC or NFL form.
"""
