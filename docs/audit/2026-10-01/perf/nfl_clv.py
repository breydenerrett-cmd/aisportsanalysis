"""NFL card CLV: NFL picks freeze no event_id; join to the multibook NFL store by team names + kickoff, then card_clv.measure_pick."""
import sys, os
from common import *
sys.path.insert(0, os.path.join(HERE, 'repo'))
from src.pipeline import snapshots
from src.report import clv, card_clv
nfl = [e for e in card_entries() if e['sport'] == 'nfl']
rows = snapshots.read_multibook(sport='nfl')
idx = clv.pregame_index(rows)
by_teams = {}
for ev, ent in idx.items():
    for r in ent['rows'][:1]:
        by_teams[(r.get('away_team'), r.get('home_team'), (ent.get('commence_time') or '')[:10])] = ev
tot = []
for e in nfl:
    ev = by_teams.get((e['raw'].get('away_team'), e['raw'].get('home_team'), (e.get('first_pitch_utc') or '')[:10]))
    pick = dict(e['raw']); pick['event_id'] = ev; pick['kind'] = 'game'
    m = card_clv.measure_pick(pick, idx) if ev else {'absence': 'NO_EVENT (team/kickoff join failed)'}
    if 'clv_bps' in m: tot.append(m['clv_bps']/100)
    print(e['rule'], e['date'], e['raw'].get('team'), e['market'], e['side'], e['price'], e['result'], 'mkt=%.3f' % e['p_mkt'],
          ('clv=%+.2f pts p_close=%.3f drift=%+.2f books=%s' % (m['clv_bps']/100, m['p_close'], (m['p_close']-e['p_mkt'])*100, m.get('books_at_close'))) if 'clv_bps' in m else m.get('absence'),
          'observed_utc=%s' % e.get('observed_utc'))
print('NFL measured %d/%d mean clv %s' % (len(tot), len(nfl), (sum(tot)/len(tot)) if tot else None))
