from common import *
import csv
cards = card_entries()
res = {r['game_pk']: r for r in csv.DictReader(open(os.path.join(D, 'mlb_results.csv'), encoding='utf-8'))}
for e in cards:
    if e['result'] == 'VOID' and (e['kind'] == 'game' or e.get('player') == 'Dylan Beavers'):
        r = e['raw']
        print(e['ledger'], e['date'], e['entry_class'], e.get('player'), r.get('game_pk'), r.get('away_team'), r.get('home_team'), r.get('team_name'), r.get('first_pitch_utc'), 'reason=', e.get('reason'))
        gp = str(r.get('game_pk'))
        if gp in res: print('   csv:', {k: res[gp][k] for k in ('date', 'away_team', 'home_team', 'away_score', 'home_score', 'game_type')})
for l in open(os.path.join(D, 'boxscores_2026.jsonl'), encoding='utf-8'):
    if 'Beavers' in l:
        r = json.loads(l); print('box', r['game_pk'], r['player_name'], r['date'], r['observed_utc'], 'h', r['h'])
s = [r for r in load(os.path.join(D, 'cards_v2_shadow_e.jsonl')) if r['kind'] == 'card_settled' and r['date'] == '2026-09-22'][0]
print('shadow_e 09-22 settled_utc', s['settled_utc'])
# 09-27 V2 fill game: search linescore by date
gp27 = [e for e in cards if e['ledger'] == 'cards_v2.jsonl' and e['result'] == 'VOID' and e['kind'] == 'game'][0]['raw']
print('09-27 fill game_pk', gp27.get('game_pk'), gp27.get('game_id'))
n = 0
for l in open(os.path.join(D, 'boxscores_2026.jsonl'), encoding='utf-8'):
    if str(gp27.get('game_pk')) in l: n += 1
print('box rows for that game_pk:', n)
