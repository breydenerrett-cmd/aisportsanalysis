"""NFL data: schedule and results, team and player weekly statistics, injury reports.

Source: the nflverse project's release files (github.com/nflverse/nflverse-data, CC BY 4.0,
attribution kept in every record's `source` and in the manifest), fetched through the one
`src.datasvc.http.PoliteFetcher`.

The record shapes, file names and which module owns what are fixed in
docs/datasvc/NFL_SCHEMA.md. Read it before changing any of them. The leakage rule and
every feature are in docs/datasvc/NFL_FEATURES.md.
"""
