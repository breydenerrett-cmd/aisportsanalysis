"""ESPN-fed leagues (NBA, WNBA, NHL, NCAAF, NCAAB, soccer): teams, games, box scores, standings, injuries.

One generic ingest for every league ESPN's public site JSON covers; a league is an entry in `leagues.py`.
  leagues.py   the league registry (ESPN path, box-score depth, which feeds exist)
  parse.py     pure functions: ESPN JSON in, normalised rows out (no I/O)
  store.py     append-only, versioned JSONL: every row carries observed_utc; a changed fact is a NEW row
  pipeline.py  refresh / backfill / rosters / status, over src.datasvc.http.PoliteFetcher
  service.py   the unified read API (also reachable as DataClient.league(code))
  cli.py       `python -m src.datasvc.cli espn ...` (and `python -m src.cli datasvc ...`)

stdlib only. Contract: docs/datasvc/ESPN_SCHEMA.md; coverage: docs/datasvc/COVERAGE_MATRIX.md.
"""
