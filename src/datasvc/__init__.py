"""LineHound's own sports data service.

A data layer we run ourselves, fed directly from public sources, stored in our
own format and served through API-shaped endpoints. LineHound is its first user;
the plan for selling access to others is in docs/DATA_SERVICE_PLAN.md.

Layout:
  http.py    one polite fetcher with an on-disk cache, used by every sport
  store.py   JSONL files with stable ordering, atomic writes and a manifest
  names.py   name normalisation and matching (accents, nicknames, ambiguity)
  ufc/       UFC, from ESPN's public JSON and UFC.com athlete pages
             (contract: docs/datasvc/UFC_SCHEMA.md)
  nfl/       NFL, from nflverse's release files
             (contract: docs/datasvc/NFL_SCHEMA.md)
  client.py  the in-process door (`DataClient`) and the fastapi-free core the /data/v1 routes call
  mlb/       MLB, wrapping the existing stores and the analyst's packet (no ingest of its own)
             (reference: docs/datasvc/CLIENT.md)

stdlib only, like the rest of src/.
"""
