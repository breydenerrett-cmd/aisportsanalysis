"""Soccer history that ESPN does not carry: results with open and closing bookmaker odds (football-data.co.uk).

  footballdata.py  CSV -> normalised rows, the versioned store, the GATED fetch (read the terms in its docstring)
  match.py         the join to ESPN game ids (date + team-name mapping) and its match-rate report
  service.py       read API: a match or an ESPN game with its odds
  cli.py           `python -m src.datasvc.cli soccer import | fetch | match | odds | status`

stdlib only. Contract: docs/datasvc/SOCCER_HISTORY.md.
"""
