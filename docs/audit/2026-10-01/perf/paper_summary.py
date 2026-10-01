"""Paper-account distribution per class (systems reported apart; only counts/quantiles across systems)."""
import collections, math
from common import *
pa = paper_entries()
by = collections.defaultdict(list)
for e in pa: by[(e['vis'], e['rule'])].append(e)
for cls in ('CONTROL', 'MARKET_REFERENCE', 'FORWARD_TEST'):
    rs = []
    for (v, r), es in by.items():
        if v != cls: continue
        st = [e for e in es if e['result'] in ('WIN', 'LOSS')]
        u = sum(e['units'] for e in st)
        rs.append((r, len(st), u, u/len(st) if st else 0, collections.Counter(e['market'] for e in es)))
    rs.sort(key=lambda x: -x[3])
    pos = sum(1 for x in rs if x[2] > 0)
    big = [x for x in rs if x[1] >= 30]
    print(cls, 'systems=%d positive-units=%d; systems with >=30 staked: %d, of which positive %d' % (len(rs), pos, len(big), sum(1 for x in big if x[2] > 0)))
    for x in big:
        z = x[2]/math.sqrt(x[1]) if x[1] else 0
        print('   %-48s staked=%3d units=%+7.2f ROI=%+6.1f%% approx z(units/sqrt(n))=%+.2f %s' % (x[0], x[1], x[2], 100*x[3], z, dict(x[4])))
odd = [e for e in pa if e['date'] and e['date'] < '2026-01-01']
print('rows dated before 2026:', len(odd), collections.Counter((e['rule'], e['date']) for e in odd))
