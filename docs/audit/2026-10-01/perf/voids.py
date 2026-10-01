"""Audit each public-card VOID: would it have graded? (box/linescore lookups, name normalisation)."""
import unicodedata, collections, csv
from common import *
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c)).lower().replace('.', '').replace(' jr', '').strip()
box = collections.defaultdict(dict); lines = {}
for l in open(os.path.join(D, 'boxscores_2026.jsonl'), encoding='utf-8'):
    r = json.loads(l)
    if r.get('type') == 'batter': box[str(r['game_pk'])][norm(r['player_name'])] = r
    elif r.get('type') == 'linescore': lines[str(r['game_pk'])] = r
res = {r['game_pk']: r for r in csv.DictReader(open(os.path.join(D, 'mlb_results.csv'), encoding='utf-8'))}
stat = {'batter_hits': 'h', 'batter_total_bases': 'total_bases', 'batter_runs_scored': 'r'}
tot = collections.Counter(); hyp = []
for e in card_entries():
    if e['result'] != 'VOID': continue
    gp = str(e.get('game_pk'))
    if e['kind'] == 'prop':
        r = box.get(gp, {}).get(norm(e['player']))
        if r is None:
            why = 'game box captured=%s; player absent (DNP or name mismatch)' % (gp in box)
            hypo = None
        else:
            v = r.get(stat[e['market']]); won = v > e['line'] if e['side'].lower() == 'over' else v < e['line']
            hypo = ((dec(e['price'])-1) if won else -1.0); why = 'box row exists: %s=%s pa=%s -> would be %s %+.2f' % (stat[e['market']], v, r.get('pa'), 'WIN' if won else 'LOSS', hypo)
    else:
        hypo = None
        why = 'csv has game=%s linescore=%s' % (gp in res, gp in lines)
    print('%-24s %s %-10s %-19s %-22s %s %s px=%s | %s' % (e['ledger'], e['date'], e['entry_class'], e['market'], e.get('player') or e.get('team') or e.get('side'), e.get('side'), e.get('line'), e['price'], why))
    if hypo is not None and e['ledger'] == 'cards_v2.jsonl': hyp.append((e['entry_class'], hypo))
print('cards_v2.jsonl VOIDs that a box row could have graded:', hyp, 'sum by class:', {c: round(sum(h for k, h in hyp if k == c), 2) for c in {k for k, _ in hyp}})
