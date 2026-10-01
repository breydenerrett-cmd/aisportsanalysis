"""Within SHADOW_A (band-only superset of V2) and V2 public shown entries: do entries passing V2's
G7 value test (marked_down(our) >= breakeven + 0.010*d/d(-160)) do better or worse than those failing it?"""
import math
from common import *
from pops import populations, staked
cards = card_entries(); P = populations(cards)
D160 = dec(-160)
def g7(e): return (e['p_our_raw'] - 0.038) >= be(e['price']) + 0.010*dec(e['price'])/D160
def g8(e): return abs(e['p_our_raw'] - e['p_mkt']) <= 0.10
def rep(lab, s):
    if not s: print('  %-40s n=0' % lab); return
    w = sum(e['result'] == 'WIN' for e in s); ex = sum(e['p_mkt'] for e in s)
    u = sum(e['units'] for e in s)
    print('  %-40s n=%3d W-L=%d-%d WR=%.3f mkt=%.3f win-mkt=%+.3f our_raw-mkt=%+.3f units=%+.2f ROI=%+.1f%%' % (lab, len(s), w, len(s)-w, w/len(s), ex/len(s), (w-ex)/len(s), sum(e['p_our_raw']-e['p_mkt'] for e in s)/len(s), u, 100*u/len(s)))
    return [(e['result'] == 'WIN') - e['p_mkt'] for e in s]
for name in ('V2shadowA picks',):
    s = [e for e in staked(P[name]) if e.get('p_our_raw') is not None and e.get('p_mkt') is not None]
    print(name)
    a = rep('passes V2 G7 value test', [e for e in s if g7(e)])
    b = rep('fails V2 G7 value test', [e for e in s if not g7(e)])
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    va = sum((x-ma)**2 for x in a)/(len(a)-1); vb = sum((x-mb)**2 for x in b)/(len(b)-1)
    print('  difference in (win-mkt) pass-fail = %+.3f, se %.3f, z %+.2f' % (ma-mb, math.sqrt(va/len(a)+vb/len(b)), (ma-mb)/math.sqrt(va/len(a)+vb/len(b))))
    rep('passes G7 and G8 (disagreement<=0.10)', [e for e in s if g7(e) and g8(e)])
    for lo, hi in ((-1, 0), (0, .04), (.04, .08), (.08, .12), (.12, 1)):
        rep('our_raw-mkt in [%+.2f,%+.2f)' % (lo, hi), [e for e in s if lo <= e['p_our_raw'] - e['p_mkt'] < hi])
pub = [e for e in staked(P['V2pub MAIN picks'] + P['V2pub fills']) if e.get('p_our_raw') is not None]
print('V2 public picks+fills')
a = rep('MAIN picks (passed G7)', staked(P['V2pub MAIN picks']))
b = rep('fills (failed G3 and/or G7)', staked(P['V2pub fills']))
ma, mb = sum(a)/len(a), sum(b)/len(b)
va = sum((x-ma)**2 for x in a)/(len(a)-1); vb = sum((x-mb)**2 for x in b)/(len(b)-1)
print('  difference in (win-mkt) picks-fills = %+.3f, se %.3f, z %+.2f' % (ma-mb, math.sqrt(va/len(a)+vb/len(b)), (ma-mb)/math.sqrt(va/len(a)+vb/len(b))))
# overlap of public V2 picks with shadow A picks
key = lambda e: (e['date'], str(e.get('game_pk')), e.get('player'), e.get('market'), e.get('side'))
A = {key(e) for e in P['V2shadowA picks']}
print('V2 public MAIN picks also in shadow A picks: %d/%d' % (sum(key(e) in A for e in P['V2pub MAIN picks']), len(P['V2pub MAIN picks'])))
