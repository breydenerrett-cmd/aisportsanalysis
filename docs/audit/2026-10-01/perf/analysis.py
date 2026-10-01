"""GOAL 2 a,b,e,f,g,h (CLV/staleness are in clv_audit.py). Output -> out_analysis.txt"""
import random, math, collections, csv, sys
from common import *
from pops import populations, staked
random.seed(20261001)
cards = card_entries()
P = populations(cards)
out = []
def pr(*a): out.append(' '.join(str(x) for x in a))
def W(e): return 1 if e['result'] == 'WIN' else 0

def brier(es, key): return sum((e[key] - W(e))**2 for e in es)/len(es)
def ll(es, key):
    s = 0
    for e in es:
        p = min(max(e[key], 1e-6), 1-1e-6)
        s += -(math.log(p) if W(e) else math.log(1-p))
    return s/len(es)
def paired_se(es, k1, k2):
    d = [(e[k1]-W(e))**2 - (e[k2]-W(e))**2 for e in es]
    m = sum(d)/len(d); v = sum((x-m)**2 for x in d)/(len(d)-1) if len(d) > 1 else 0
    return m, math.sqrt(v/len(d))
def mean(xs):
    xs = list(xs); return sum(xs)/len(xs) if xs else float('nan')

pr('== (a) CALIBRATION: our frozen number vs de-vigged market_probability on IDENTICAL staked entries')
pr('V2 "our" = our_probability_used (after 0.038 markdown); raw = our_probability')
for name, es in P.items():
    s = [e for e in staked(es) if e.get('p_our') is not None and e.get('p_mkt') is not None]
    s2 = staked(es)
    if not s:
        if s2: pr('  %-20s n=%d no our/mkt pair (our on %d, mkt on %d)' % (name, len(s2), sum(e.get('p_our') is not None for e in s2), sum(e.get('p_mkt') is not None for e in s2)))
        continue
    m, se = paired_se(s, 'p_our', 'p_mkt')
    line = '  %-20s n=%3d WR=%.3f mOur=%.3f mMkt=%.3f Brier our=%.4f mkt=%.4f d=%+.4f+-%.4f LL our=%.4f mkt=%.4f' % (
        name, len(s), mean(W(e) for e in s), mean(e['p_our'] for e in s), mean(e['p_mkt'] for e in s),
        brier(s, 'p_our'), brier(s, 'p_mkt'), m, se, ll(s, 'p_our'), ll(s, 'p_mkt'))
    if s[0]['ledger'].startswith('cards_v2'):
        line += ' | raw mean=%.3f Brier=%.4f LL=%.4f' % (mean(e['p_our_raw'] for e in s), brier(s, 'p_our_raw'), ll(s, 'p_our_raw'))
    pr(line)

pr('\n-- calibration buckets on OUR number (within one population only)')
edges = [0, .45, .5, .55, .6, .65, .7, .75, 1.01]
for name in ['V1pub games pick', 'V1pub props hits', 'V1pub props TB', 'V1shadow games pick', 'V1shadow props hits', 'V1shadow props TB', 'V2pub MAIN picks', 'V2pub fills', 'V2shadowA picks']:
    s = [e for e in staked(P[name]) if e.get('p_our') is not None]
    pr('  ' + name + ' n=%d' % len(s))
    for lo, hi in zip(edges, edges[1:]):
        b = [e for e in s if lo <= e['p_our'] < hi]
        if not b: continue
        pm = [e['p_mkt'] for e in b if e['p_mkt'] is not None]
        pr('    our [%.2f,%.2f): n=%3d mean_our=%.3f mean_mkt=%.3f realised=%.3f units=%+.2f' % (lo, min(hi, 1), len(b), mean(e['p_our'] for e in b), mean(pm), mean(W(e) for e in b), sum(e['units'] for e in b)))

pr('\n-- calibration buckets on the MARKET number, same entries')
for name in ['V1pub games pick', 'V1pub props hits', 'V1pub props TB', 'V2pub MAIN picks', 'V2pub fills']:
    s = [e for e in staked(P[name]) if e.get('p_mkt') is not None]
    pr('  ' + name + ' n=%d' % len(s))
    for lo, hi in zip(edges, edges[1:]):
        b = [e for e in s if lo <= e['p_mkt'] < hi]
        if not b: continue
        pr('    mkt [%.2f,%.2f): n=%3d mean_mkt=%.3f realised=%.3f' % (lo, min(hi, 1), len(b), mean(e['p_mkt'] for e in b), mean(W(e) for e in b)))

pr('\n-- does raw (our - market) predict (win - market)? OLS slope (1.0 = our disagreement fully real, 0 = noise)')
for name in ['V1pub games pick', 'V1pub props hits', 'V1pub props TB', 'V1shadow props hits', 'V2pub MAIN picks', 'V2pub fills', 'V2shadowA picks']:
    s = [e for e in staked(P[name]) if e.get('p_our_raw') is not None and e.get('p_mkt') is not None]
    if len(s) < 5: continue
    x = [e['p_our_raw'] - e['p_mkt'] for e in s]; y = [W(e) - e['p_mkt'] for e in s]
    mx, my = mean(x), mean(y)
    sxx = sum((a-mx)**2 for a in x); sxy = sum((a-mx)*(b-my) for a, b in zip(x, y))
    slope = sxy/sxx if sxx else float('nan')
    res = [b-my-slope*(a-mx) for a, b in zip(x, y)]
    se = math.sqrt(sum(r*r for r in res)/(len(s)-2)/sxx) if sxx and len(s) > 2 else float('nan')
    pr('  %-20s n=%3d mean(our_raw-mkt)=%+.3f mean(win-mkt)=%+.3f slope=%+.2f se=%.2f' % (name, len(s), mx, my, slope, se))

pr('\n== (b) PRICE/VIG: hold = breakeven(price) - de-vigged market_probability at freeze')
for name, es in P.items():
    s = [e for e in staked(es) if e.get('p_mkt') is not None and be(e['price'])]
    if not s: continue
    hold = [be(e['price']) - e['p_mkt'] for e in s]
    fair = sum((1/e['p_mkt'] - 1) if W(e) else -1 for e in s)
    act = sum(e['units'] for e in s)
    ev = sum(e['p_mkt']*(dec(e['price'])-1) - (1-e['p_mkt']) for e in s)
    pr('  %-20s n=%3d hold mean=%+.4f [min %+.4f max %+.4f] units=%+.2f at-fair=%+.2f (vig cost %.2f u) E[units|mkt right]=%+.2f (%+.1f%%/bet)' % (
        name, len(s), mean(hold), min(hold), max(hold), act, fair, fair-act, ev, 100*ev/len(s)))

pr('\n== (e) SELECTION / POPULATION SHIFT (staked entries)')
def popdesc(name, es):
    s = staked(es)
    if not s: return
    fav = mean(1 if e['price'] < 0 else 0 for e in s)
    plus = mean(1 if e['price'] > 0 else 0 for e in s)
    prop = mean(1 if e['kind'] == 'prop' else 0 for e in s)
    md = mean(dec(e['price']) for e in s)
    bes = mean(be(e['price']) for e in s)
    wr = mean(W(e) for e in s); u = sum(e['units'] for e in s)
    pm = [e for e in s if e['p_mkt'] is not None]
    ev = sum(e['p_mkt']*(dec(e['price'])-1) - (1-e['p_mkt']) for e in pm)
    exw = sum(e['p_mkt'] for e in pm)
    pr('  %-34s n=%3d W-L=%d-%d fav=%.0f%% plus=%.0f%% prop=%.0f%% meanPx=%+.0f breakevenWR=%.3f realisedWR=%.3f units=%+.2f ROI=%+.1f%% | expected wins at mkt=%.1f actual=%d  E[units|mkt]=%+.2f  luck(actual-E)=%+.2f' % (
        name, len(s), sum(W(e) for e in s), len(s)-sum(W(e) for e in s), 100*fav, 100*plus, 100*prop, dec_to_american(md), bes, wr, u, 100*u/len(s),
        exw, sum(W(e) for e in pm), ev, u - sum(e['units'] for e in pm) + 0 + (sum(e['units'] for e in pm) - ev)))
V1all = [e for e in cards if e['ledger'] == 'cards_v1.jsonl']
popdesc('V1 public ALL (games+SPLIT+props)', V1all)
popdesc('V1 public games (pick+SPLIT)', [e for e in V1all if e['kind'] == 'game'])
popdesc('V1 public props', [e for e in V1all if e['kind'] == 'prop'])
for b in ['<=-160', '-159..-100']:
    popdesc('V1 public games band ' + b, [e for e in V1all if e['kind'] == 'game' and band(e['price']) == b])
    popdesc('V1 public props band ' + b, [e for e in V1all if e['kind'] == 'prop' and band(e['price']) == b])
popdesc('V1 shadow ALL', [e for e in cards if e['ledger'] == 'cards_v1_shadow.jsonl'])
V2pub = [e for e in cards if e['ledger'] == 'cards_v2.jsonl']
popdesc('V2 public picks (MAIN+PLUS)', [e for e in V2pub if e['entry_class'] == 'pick'])
popdesc('V2 public MAIN picks', P['V2pub MAIN picks'])
popdesc('V2 public fills', P['V2pub fills'])
popdesc('V2 public picks+fills (shown)', [e for e in V2pub if e['entry_class'] in ('pick', 'fill')])
popdesc('V2 shadow A picks', P['V2shadowA picks'])
popdesc('V2 shadow C picks', P['V2shadowC picks'])
popdesc('V2 shadow C fills', P['V2shadowC fills'])
popdesc('V2 shadow E picks', P['V2shadowE picks'])
popdesc('V2 shadow E fills', P['V2shadowE fills'])
# V2 published composition (all shown entries, incl. unstaked) by market & class
pr('  V2 public shown-entry composition (all results):')
c = collections.Counter((e['entry_class'], e.get('price_class'), mkt_label(e)) for e in V2pub)
for k, v in sorted(c.items(), key=lambda kv: str(kv[0])): pr('    ', k, v)
pr('  V2 public fills: failed_gates distribution:', collections.Counter(tuple(e['raw'].get('failed_gates') or ()) for e in P['V2pub fills']))
pr('  V2 public fills W-L by failed gate:')
for g in ('G3_STALE', 'G7_VALUE'):
    s = [e for e in staked(P['V2pub fills']) if g in (e['raw'].get('failed_gates') or ())]
    pr('    %s: n=%d W=%d units=%+.2f' % (g, len(s), sum(W(e) for e in s), sum(e['units'] for e in s)))

pr('\n== (f) VARIANCE: V2 public MAIN picks')
s = staked(P['V2pub MAIN picks'])
u = sum(e['units'] for e in s); n = len(s)
pr('  n staked=%d units=%+.3f ROI=%+.2f%%  (voids not staked: %d)' % (n, u, 100*u/n, sum(e['result'] == 'VOID' for e in P['V2pub MAIN picks'])))
bydate = collections.defaultdict(list)
for e in s: bydate[e['date']].append(e)
dates = sorted(bydate)
pr('  dates:', {d: (len(bydate[d]), round(sum(e['units'] for e in bydate[d]), 2)) for d in dates})
B = 100000; rois = []
for _ in range(B):
    ds = [random.choice(dates) for _ in dates]
    es = [e for d in ds for e in bydate[d]]
    rois.append(sum(e['units'] for e in es)/len(es))
rois.sort()
pr('  bootstrap over %d dates (B=%d): ROI 95%% CI [%+.1f%%, %+.1f%%], median %+.1f%%' % (len(dates), B, 100*rois[int(.025*B)], 100*rois[int(.975*B)], 100*rois[B//2]))
rois2 = []
for _ in range(B):
    es = [random.choice(s) for _ in s]
    rois2.append(sum(e['units'] for e in es)/len(es))
rois2.sort()
pr('  bootstrap over picks: ROI 95%% CI [%+.1f%%, %+.1f%%]' % (100*rois2[int(.025*B)], 100*rois2[int(.975*B)]))
for r in (0.0, -0.045):
    cnt = 0; sims = 200000
    qs = [(1+r)/dec(e['price']) for e in s]; ds_ = [dec(e['price']) for e in s]
    for _ in range(sims):
        tot = 0.0
        for q, d in zip(qs, ds_):
            tot += (d-1) if random.random() < q else -1
        if tot <= u + 1e-9: cnt += 1
    pr('  P(units <= %+.2f | true ROI=%+.1f%%) = %.3f  (MC %d sims, per-pick win prob=(1+ROI)/decimal)' % (u, 100*r, cnt/sims, sims))
sd = math.sqrt(sum((dec(e['price'])-1)**2*(1/dec(e['price']))*(1-1/dec(e['price'])) + 0 for e in s))
pr('  approx SD of units at fair odds = %.2f u (ROI SD %.1f%%)' % (sd, 100*sd/n))
out.pop()   # replace the SD line above with the correct variance q(1-q)d^2
sd = math.sqrt(sum(dec(e['price'])**2 * (1/dec(e['price'])) * (1 - 1/dec(e['price'])) for e in s))
pr('  SD of units if every pick were a fair (zero-EV) bet = %.2f u -> ROI SD %.1f%%; observed ROI is %.2f SD from 0' % (sd, 100*sd/n, u/sd))

pr('\n== (g) SETTLEMENT / DATA: VOID + UNRESOLVED reasons, all card ledgers (newest settled row per date)')
c = collections.Counter()
for e in cards:
    if e['result'] in ('VOID', 'UNRESOLVED'):
        c[(e['ledger'], e['result'], e['market'], e['entry_class'], e.get('reason') or '(no reason field on graded entry)')] += 1
for k, v in sorted(c.items()): pr('  %3d  %s' % (v, ' | '.join(str(x) for x in k)))
pr('  batter_runs_scored entries (all ledgers):')
for e in cards:
    if e['market'] == 'batter_runs_scored':
        pr('    %s %s %s %s %s %s line=%s px=%s -> %s (%s)' % (e['ledger'], e['date'], e['entry_class'], e.get('player'), e.get('side'), e.get('game_pk'), e.get('line'), e.get('price'), e['result'], e.get('reason')))
# multiple settled rows per date?
for f in ['cards_v1.jsonl', 'cards_v1_shadow.jsonl', 'cards_v2.jsonl', 'cards_v2_shadow_a.jsonl', 'cards_v2_shadow_c.jsonl', 'cards_v2_shadow_e.jsonl', 'cards_nfl_v1.jsonl']:
    rows = load(os.path.join(D, f))
    cc = collections.Counter(r['date'] for r in rows if r['kind'] == 'card_settled')
    pubd = {r['date'] for r in rows if r['kind'] == 'card_published'}
    pr('  %-26s settled rows/date max=%d; published dates without settled row: %s' % (f, max(cc.values()), sorted(pubd - set(cc))))

pr('\n  spot-check: card game entries vs data/historical/mlb_results.csv (origin) and boxscores_2026 linescores')
res = {}
for r in csv.DictReader(open(os.path.join(D, 'mlb_results.csv'), encoding='utf-8')):
    res[r['game_pk']] = r
lines = {}; teams = collections.defaultdict(dict)
for l in open(os.path.join(D, 'boxscores_2026.jsonl'), encoding='utf-8'):
    r = json.loads(l)
    if r.get('type') == 'linescore': lines[str(r['game_pk'])] = r
    elif r.get('type') == 'batter': teams[str(r['game_pk'])][r['side']] = r.get('team_name')
games = [e for e in cards if e['kind'] == 'game' and e['sport'] == 'mlb' and e['result'] in ('WIN', 'LOSS', 'PUSH')]
random.seed(7)
sample = random.sample(games, 10) + [e for e in games if e['ledger'] == 'cards_v2.jsonl'][:0]
mism = 0; checked = 0
for e in games:
    gp = str(e['game_pk']); a = h = None; src = None
    if gp in res: a, h, src = int(res[gp]['away_score']), int(res[gp]['home_score']), 'csv'
    elif gp in lines:
        a = sum(i.get('away_runs') or 0 for i in lines[gp]['innings']); h = sum(i.get('home_runs') or 0 for i in lines[gp]['innings']); src = 'linescore'
    if a is None: continue
    checked += 1
    side = e['side']; m = h - a
    if e['market'] in ('run_line', 'spread'):
        adj = (m if side == 'home' else -m) + float(e['line']); won = adj > 0
    else:
        won = (m > 0) if side == 'home' else (m < 0)
    team_ok = True
    if gp in res and e.get('team'):
        team_ok = e['team'] == (res[gp]['home_team'] if side == 'home' else res[gp]['away_team'])
    ok = (won == (e['result'] == 'WIN')) and team_ok
    if not ok: mism += 1
    if e in sample or not ok:
        pr('    %s %s %s %s %s %s px=%s | ledger %s | %s %d-%d team_ok=%s -> %s' % (e['ledger'], e['date'], gp, e['market'], e.get('team'), side, e['price'], e['result'], src, a, h, team_ok, 'OK' if ok else 'MISMATCH'))
pr('  game entries re-graded independently: %d checked, %d mismatches (of %d graded game entries)' % (checked, mism, len(games)))
# props vs box
box = {}
for l in open(os.path.join(D, 'boxscores_2026.jsonl'), encoding='utf-8'):
    r = json.loads(l)
    if r.get('type') == 'batter': box[(str(r['game_pk']), r['player_name'])] = r
statf = {'batter_hits': 'h', 'batter_total_bases': 'total_bases', 'batter_runs_scored': 'r'}
pm = 0; pc = 0; nobox = 0
for e in cards:
    if e['kind'] != 'prop' or e['result'] not in ('WIN', 'LOSS', 'PUSH'): continue
    r = box.get((str(e['game_pk']), e['player']))
    if r is None: nobox += 1; continue
    v = r.get(statf[e['market']]); pc += 1
    won = v > e['line'] if str(e['side']).lower() == 'over' else v < e['line']
    if won != (e['result'] == 'WIN'):
        pm += 1; pr('    PROP MISMATCH', e['ledger'], e['date'], e['player'], e['market'], e['side'], e['line'], 'stat', v, e['result'])
pr('  prop entries re-graded vs boxscores_2026: %d checked, %d mismatches, %d with no box row in origin store' % (pc, pm, nobox))

pr('\n== (h) PROPS: price level and per-market calibration')
for name in ['V1pub props hits', 'V1pub props TB', 'V1shadow props hits', 'V1shadow props TB']:
    s = staked(P[name])
    pr('  %-20s n=%3d W-L=%d-%d WR=%.3f meanPx=%+.0f breakeven=%.3f mkt=%.3f our=%.3f units=%+.2f ROI=%+.1f%%  sides=%s lines=%s' % (
        name, len(s), sum(W(e) for e in s), len(s)-sum(W(e) for e in s), mean(W(e) for e in s), dec_to_american(mean(dec(e['price']) for e in s)),
        mean(be(e['price']) for e in s), mean(e['p_mkt'] for e in s if e['p_mkt'] is not None), mean(e['p_our'] for e in s if e['p_our'] is not None),
        sum(e['units'] for e in s), 100*sum(e['units'] for e in s)/len(s), dict(collections.Counter(e['side'] for e in s)), dict(collections.Counter(e['line'] for e in s))))
s = staked([e for e in cards if e['ledger'] == 'cards_v1.jsonl' and e['kind'] == 'prop'])
pr('  V1 public props combined: W-L %d-%d WR=%.3f vs breakeven %.3f; units %+.2f; average win pays %.3f u, loss costs 1 u' % (
    sum(W(e) for e in s), len(s)-sum(W(e) for e in s), mean(W(e) for e in s), mean(be(e['price']) for e in s), sum(e['units'] for e in s), mean(e['units'] for e in s if W(e))))
pr('  V1 public props: books per prop quote:', dict(collections.Counter(e.get('books') for e in s)))
pr('  V2 public picks props: books per quote:', dict(collections.Counter(e.get('books') for e in P['V2pub MAIN picks'])))

txt = '\n'.join(out)
open(os.path.join(HERE, 'out_analysis.txt'), 'w', encoding='utf-8').write(txt)
print(txt)
