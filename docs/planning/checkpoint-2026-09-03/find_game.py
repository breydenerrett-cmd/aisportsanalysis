from src.evolab import replay
u = replay.load_universe(seasons=(2023,))
best = None
for g in u.games:
    a = g.features.get("away_lineup_platoon_share")
    h = g.features.get("home_lineup_platoon_share")
    if a is None or h is None:
        continue
    d = a - h
    if abs(d) >= 0.334 and g.instants:
        print(g.game_pk, g.away_team, g.home_team, g.official_date, "diff=", d)
        best = g
        if best:
            break
