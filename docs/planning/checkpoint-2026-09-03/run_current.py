import json, sys
from src.engine import glue as glue_module
from src.engine.analyze import analyze, DEFAULT_CONFIG
from src.engine.adversaries import DEFAULT_ADVERSARIES
from dataclasses import asdict

date_str = "2026-09-02"
games = glue_module.games_captured_on(date_str)
print("games captured on", date_str, ":", len(games), file=sys.stderr)
game = games[0]
t = glue_module.latest_capture_time(game, date_str)
print("game=", game, "t=", t, file=sys.stderr)

board = glue_module.build_board(game, t)
snapshot = glue_module.build_snapshot(game, t, board=board)
print("snapshot.available_markets=", snapshot.available_markets, file=sys.stderr)
print("snapshot.books_by_market=", snapshot.books_by_market, file=sys.stderr)
print("snapshot.features=", snapshot.features, file=sys.stderr)
print("snapshot.assumption_exposure=", snapshot.assumption_exposure, file=sys.stderr)
print("snapshot.lineup_posted=", snapshot.lineup_posted, file=sys.stderr)
print("board.selections()=", board.selections()[:10], file=sys.stderr)

systems = (glue_module.TrivialAlwaysHomeSystem(),)
analysis = analyze(snapshot, board, systems=systems, adversaries=DEFAULT_ADVERSARIES, config=DEFAULT_CONFIG)
print("n records:", len(analysis.records), file=sys.stderr)
for rec in analysis.records[:2]:
    print(json.dumps(asdict(rec), indent=2, default=str))
