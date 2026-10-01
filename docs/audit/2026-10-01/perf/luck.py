"""Wins vs market-implied expectation (z) per population; paper-account sealed-window rows."""
import math, collections
from common import *
from pops import populations, staked
cards = card_entries(); P = populations(cards)
def rep(name, es):
    s = [e for e in staked(es) if e.get('p_mkt') is not None]
    if not s: return
    w = sum(e['result'] == 'WIN' for e in s); ex = sum(e['p_mkt'] for e in s); sd = math.sqrt(sum(e['p_mkt']*(1-e['p_mkt']) for e in s))
    exb = sum(be(e['price']) for e in s)
    print('%-34s n=%3d wins=%3d E[wins|de-vig mkt]=%.1f z=%+.2f  E[wins|breakeven]=%.1f z_vs_breakeven=%+.2f' % (name, len(s), w, ex, (w-ex)/sd, exb, (w-exb)/sd))
V1 = [e for e in cards if e['ledger'] == 'cards_v1.jsonl']
rep('V1 public all', V1)
rep('V1 public games', [e for e in V1 if e['kind'] == 'game'])
rep('V1 public games <=-160', [e for e in V1 if e['kind'] == 'game' and e['price'] <= -160])
rep('V1 public games -159..-100', [e for e in V1 if e['kind'] == 'game' and -160 < e['price'] <= -100])
rep('V1 public props', [e for e in V1 if e['kind'] == 'prop'])
rep('V1 shadow all', [e for e in cards if e['ledger'] == 'cards_v1_shadow.jsonl'])
for k in ('V2pub MAIN picks', 'V2pub fills', 'V2shadowA picks', 'V2shadowC fills', 'V2shadowE fills'):
    rep(k, P[k])
pa = paper_entries()
early = [e for e in pa if e['date'] and e['date'] < '2026-08-28']
print('paper rows dated inside sealed window 2026-01-01..2026-08-27:', len(early), collections.Counter(e['rule'] for e in early), sorted({e['date'] for e in early})[:5])
