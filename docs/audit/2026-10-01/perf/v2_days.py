"""V2 public: per-date composition of the newest published row and gate failures of close calls."""
import collections
from common import *
rows = load(os.path.join(D, 'cards_v2.jsonl'))
last = {}
cnt = collections.Counter()
for r in rows:
    if r['kind'] == 'card_published':
        last[r['date']] = r; cnt[r['date']] += 1
for d, r in sorted(last.items()):
    ab = r.get('all_bets') or []
    cc = r.get('close_calls_not_shown') or []
    g = collections.Counter(x for c in cc for x in (c.get('failed_gates') or []))
    pr = collections.Counter((e.get('entry_class'), e.get('kind') if e.get('kind') == 'prop' else 'game') for e in ab)
    print(d, 'publishes=%d' % cnt[d], 'all_bets=%d' % len(ab), dict(pr), 'withdrawn=%d' % len(r.get('withdrawn') or []), 'stale_board=%s' % r.get('stale_board'),
          'ceiling_refused=%d' % len(r.get('ceiling_refused') or []), 'close_calls=%d' % len(cc), 'gate fails among close calls:', dict(g.most_common(6)))
