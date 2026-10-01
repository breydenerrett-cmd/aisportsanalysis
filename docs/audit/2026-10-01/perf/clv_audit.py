"""GOAL 2 c (CLV), d (staleness), b (best price at freeze). Reuses origin's
src.report.card_clv.measure_pick / src.report.clv.pregame_index read-only (exported copy in ./repo).
Output -> out_clv.txt"""
import sys, os, json, math, collections
from common import *
from pops import populations, staked
sys.path.insert(0, os.path.join(HERE, 'repo'))
from src.pipeline import snapshots
from src.report import clv, card_clv

cards = card_entries()
P = populations(cards)
out = []
def pr(*a): out.append(' '.join(str(x) for x in a))
def mean(xs):
    xs = list(xs); return sum(xs)/len(xs) if xs else float('nan')
def W(e): return 1 if e['result'] == 'WIN' else 0

# event_id for entries that froze none (all V1 game picks, V2 props)
emap = {}
for r in load(os.path.join(HERE, 'repo', 'data', 'processed', 'event_game_map.jsonl')):
    if r.get('resolved') and r.get('event_id') and r.get('game_pk') is not None:
        emap[str(r['game_pk'])] = r['event_id']
for e in cards:
    if not e.get('event_id') and e.get('game_pk') is not None:
        e['event_id'] = emap.get(str(e['game_pk']))
        e['event_id_source'] = 'event_game_map' if e['event_id'] else None
    else:
        e['event_id_source'] = 'frozen'

rows = snapshots.read_multibook()
index = clv.pregame_index(rows)
nfl_rows = snapshots.read_multibook(sport='nfl')
nfl_index = clv.pregame_index(nfl_rows)
pr('multibook rows mlb=%d (events with pre-game rows %d); nfl rows=%d events=%d' % (len(rows), len(index), len(nfl_rows), len(nfl_index)))

def measure(e):
    if e['kind'] == 'prop':
        return {'absence': 'PROP (see relaxed prop close below)'}
    pick = dict(e['raw'])
    pick['event_id'] = e.get('event_id')
    pick['kind'] = 'game'
    pick.setdefault('entry_class', e['entry_class']); pick.setdefault('price_class', e.get('price_class'))
    if e['sport'] == 'nfl':
        mk = pick.get('market')
        if mk not in ('moneyline', 'run_line'):
            return {'absence': 'NFL market %s has no card_clv market key' % mk}
        return card_clv.measure_pick(pick, nfl_index)
    return card_clv.measure_pick(pick, index)

for e in cards:
    e['clv'] = measure(e)

# best price on the board at the freeze instant (game entries)
def board_at(e):
    ent = (nfl_index if e['sport'] == 'nfl' else index).get(e.get('event_id'))
    obs = ts(e.get('observed_utc'))
    if not ent or obs is None: return None
    mk = {'moneyline': None, 'run_line': 'spreads'}.get(e['market'], 'x')
    if mk == 'x': return None
    cand = [r for r in ent['rows'] if r.get('market') == mk and ts(r.get('observed_utc')) is not None and ts(r['observed_utc']) <= obs]
    if not cand: return None
    inst = max(ts(r['observed_utc']) for r in cand)
    q = [r for r in cand if ts(r['observed_utc']) == inst]
    side = e['side']; pf = side + '_price'
    if mk == 'spreads':
        q = [r for r in q if r.get(side + '_line') == e.get('line')]
    px = [r.get(pf) for r in q if r.get(pf) is not None]
    return (inst, px, (obs - inst).total_seconds()) if px else None
for e in cards:
    e['best'] = None
    if e['kind'] == 'game' and e['result'] in ('WIN', 'LOSS'):
        b = board_at(e)
        if b: e['best'] = b

pr('\n== (c) CLV, game entries: card_clv.measure_pick (close = last multibook pre-game instant; de-vigged; >=%d books)' % clv.MIN_BOOKS)
pr('   clv_pts = p_close(de-vigged) - breakeven(frozen price)  [positive = beat the fair close]; drift_pts = p_close - frozen market_probability')
def clv_report(name, es):
    g = [e for e in es if e['kind'] == 'game']
    if not g: return
    ok = [e for e in g if 'clv_bps' in e['clv']]
    ab = collections.Counter(e['clv'].get('absence') for e in g if 'clv_bps' not in e['clv'])
    if ok:
        c = [e['clv']['clv_bps']/100 for e in ok]
        dr = [(e['clv']['p_close'] - e['p_mkt'])*100 for e in ok if e.get('p_mkt') is not None]
        beat = mean(1 if e['clv']['beats_close'] else 0 for e in ok)
        sd = math.sqrt(sum((x-mean(c))**2 for x in c)/(len(c)-1)) if len(c) > 1 else float('nan')
        pr('  %-22s game n=%3d measured=%3d mean clv=%+.2f pts (se %.2f) beat close=%.0f%% mean drift=%+.2f pts | absences %s' % (name, len(g), len(ok), mean(c), sd/math.sqrt(len(c)) if len(c) > 1 else float('nan'), 100*beat, mean(dr), dict(ab)))
    else:
        pr('  %-22s game n=%3d measured=0 | absences %s' % (name, len(g), dict(ab)))
for name, es in P.items():
    clv_report(name, es)
pr('  by market (V1 public games):', {m: len([e for e in P['V1pub games pick'] if e['market'] == m]) for m in ('moneyline', 'run_line')})
# CLV vs outcome
pr('\n  does CLV sign predict result? (all measured MLB game entries, each ledger kept apart)')
for led in ['cards_v1.jsonl', 'cards_v1_shadow.jsonl', 'cards_v2.jsonl', 'cards_v2_shadow_a.jsonl', 'cards_v2_shadow_c.jsonl']:
    ok = [e for e in cards if e['ledger'] == led and 'clv_bps' in e['clv'] and e['result'] in ('WIN', 'LOSS')]
    for sgn, lab in ((1, 'beat'), (0, 'missed')):
        s = [e for e in ok if (e['clv']['beats_close']) == bool(sgn)]
        if s: pr('    %-24s %-6s n=%3d WR=%.3f units=%+.2f ROI=%+.1f%%' % (led, lab, len(s), mean(W(e) for e in s), sum(e['units'] for e in s), 100*sum(e['units'] for e in s)/len(s)))

pr('\n== (b2) BEST PRICE ON THE BOARD at the freeze instant vs the frozen price (game entries)')
for name, es in P.items():
    s = [e for e in staked(es) if e.get('best')]
    if not s: continue
    fz = sum(e['units'] for e in s)
    bu = sum((max(dec(p) for p in e['best'][1]) - 1) if W(e) else -1 for e in s)
    gap = mean(be(e['price']) - 1/max(dec(p) for p in e['best'][1]) for e in s)
    lag = mean(e['best'][2] for e in s)
    worse = sum(1 for e in s if dec(e['price']) < max(dec(p) for p in e['best'][1]) - 1e-9)
    pr('  %-22s n=%3d units frozen=%+.2f at-best-book=%+.2f (diff %+.2f) mean implied-prob gap frozen-vs-best=%+.4f; frozen worse than best on %d/%d; board lag %.0fs' % (name, len(s), fz, bu, bu-fz, gap, worse, len(s), lag))

pr('\n== (c2) RELAXED PROP CLOSE (NOT the project metric: card_clv refuses props, PROP_NOT_MEASURED, six-book floor)')
pr('   close instant = last batter_props capture for (event, market) before commence; quotes for the same player+line at that instant;')
pr('   per-book proportional de-vig of the Over/Under pair, averaged across books; >=1 two-sided book required; books reported')
props = [e for e in cards if e['kind'] == 'prop' and e.get('event_id')]
need_ev = {e['event_id'] for e in props}
need_mk = {e['market'] for e in props}
byem = collections.defaultdict(list)
final_ct = {}
with open(os.path.join(D, 'batter_props.jsonl'), encoding='utf-8') as fh:
    for line in fh:
        if not any(ev in line for ev in ()) and '"event_id": "' not in line and '"event_id":"' not in line:
            continue
        r = json.loads(line)
        ev = r.get('event_id')
        if ev not in need_ev or r.get('market') not in need_mk: continue
        o = ts(r.get('observed_utc')); c = ts(r.get('commence_time'))
        if o is None or c is None: continue
        prev = final_ct.get(ev)
        if prev is None or o > prev[0]: final_ct[ev] = (o, c)
        byem[(ev, r['market'])].append((o, c, r))
def prop_close(e):
    key = (e['event_id'], e['market'])
    rs = byem.get(key)
    if not rs: return {'absence': 'NO_PROP_CAPTURE_FOR_EVENT_MARKET'}
    cut = final_ct[e['event_id']][1]
    pre = [(o, r) for o, c, r in rs if o < c and o < cut]
    if not pre: return {'absence': 'NO_PREGAME_PROP_CAPTURE'}
    inst = max(o for o, r in pre)
    q = [r for o, r in pre if o == inst and r.get('player') == e['player'] and float(r.get('line')) == float(e['line'])]
    books = collections.defaultdict(dict)
    for r in q: books[r['book']][r['side'].lower()] = r['price']
    fair = []
    for b, sd in books.items():
        if 'over' in sd and 'under' in sd:
            io, iu = be(sd['over']), be(sd['under'])
            if io and iu: fair.append((io if e['side'].lower() == 'over' else iu)/(io+iu))
    if not fair: return {'absence': 'PLAYER_LINE_NOT_TWO_SIDED_AT_CLOSE', 'inst': inst}
    obs = ts(e.get('observed_utc'))
    if obs and inst <= obs: return {'absence': 'CLOSE_NOT_AFTER_DECISION'}
    pc = mean(fair)
    return {'p_close': pc, 'books': len(fair), 'clv_pts': (pc - be(e['price']))*100, 'lead_min': (cut - inst).total_seconds()/60}
for e in cards:
    if e['kind'] == 'prop':
        e['pclv'] = prop_close(e) if e.get('event_id') else {'absence': 'NO_EVENT_ID'}
for name, es in P.items():
    g = [e for e in es if e['kind'] == 'prop']
    if not g: continue
    ok = [e for e in g if 'p_close' in e['pclv']]
    ab = collections.Counter(e['pclv'].get('absence') for e in g if 'p_close' not in e['pclv'])
    if ok:
        c = [e['pclv']['clv_pts'] for e in ok]
        dr = [(e['pclv']['p_close'] - e['p_mkt'])*100 for e in ok if e.get('p_mkt') is not None]
        sd = math.sqrt(sum((x-mean(c))**2 for x in c)/(len(c)-1)) if len(c) > 1 else float('nan')
        pr('  %-22s prop n=%3d measured=%3d mean clv=%+.2f pts (se %.2f) beat close=%.0f%% drift=%+.2f pts books@close median=%s lead_min median=%.0f | absences %s' % (
            name, len(g), len(ok), mean(c), sd/math.sqrt(len(c)) if len(c) > 1 else float('nan'), 100*mean(1 if x > 0 else 0 for x in c), mean(dr),
            sorted(e['pclv']['books'] for e in ok)[len(ok)//2], sorted(e['pclv']['lead_min'] for e in ok)[len(ok)//2], dict(ab)))
    else:
        pr('  %-22s prop n=%3d measured=0 | absences %s' % (name, len(g), dict(ab)))
for mk in ('batter_hits', 'batter_total_bases'):
    for led in ('cards_v1.jsonl', 'cards_v1_shadow.jsonl', 'cards_v2.jsonl'):
        ok = [e for e in cards if e['ledger'] == led and e['market'] == mk and 'p_close' in (e.get('pclv') or {}) and e['entry_class'] in ('pick',)]
        if ok: pr('    %-22s %-19s picks measured=%3d mean clv=%+.2f pts beat=%.0f%%' % (led, mk, len(ok), mean(e['pclv']['clv_pts'] for e in ok), 100*mean(1 if e['pclv']['clv_pts'] > 0 else 0 for e in ok)))

pr('\n== (d) STALENESS: price age = first_pitch - observed_utc (min); quote age at lock = locked_at - observed_utc (min)')
def clvpts(e):
    if 'clv_bps' in (e.get('clv') or {}): return e['clv']['clv_bps']/100
    if 'p_close' in (e.get('pclv') or {}): return e['pclv']['clv_pts']
    return None
for name in ['V1pub games pick', 'V1pub props hits', 'V1pub props TB', 'V1shadow games pick', 'V1shadow props hits', 'V2pub MAIN picks', 'V2pub fills', 'V2shadowA picks', 'V2shadowC fills']:
    s = [e for e in staked(P[name]) if ts(e.get('observed_utc')) and ts(e.get('first_pitch_utc'))]
    if len(s) < 6: continue
    for e in s:
        e['age_fp'] = (ts(e['first_pitch_utc']) - ts(e['observed_utc'])).total_seconds()/60
        e['age_lock'] = (ts(e['locked_at']) - ts(e['observed_utc'])).total_seconds()/60 if ts(e.get('locked_at')) else None
    med = sorted(e['age_fp'] for e in s)[len(s)//2]
    al = [e['age_lock'] for e in s if e['age_lock'] is not None]
    pr('  %s n=%d  price-age-at-first-pitch median=%.0f min [min %.0f max %.0f]; quote-age-at-lock median=%s min [max %s]' % (
        name, len(s), med, min(e['age_fp'] for e in s), max(e['age_fp'] for e in s),
        ('%.0f' % sorted(al)[len(al)//2]) if al else 'n/a', ('%.0f' % max(al)) if al else 'n/a'))
    for lab, sub in (('fresh (<= median)', [e for e in s if e['age_fp'] <= med]), ('stale (> median)', [e for e in s if e['age_fp'] > med])):
        cv = [clvpts(e) for e in sub if clvpts(e) is not None]
        pr('     %-18s n=%3d WR=%.3f mkt=%.3f win-mkt=%+.3f units=%+.2f ROI=%+.1f%% clv=%s (n=%d)' % (lab, len(sub), mean(W(e) for e in sub), mean(e['p_mkt'] for e in sub if e['p_mkt'] is not None),
            mean(W(e) - e['p_mkt'] for e in sub if e['p_mkt'] is not None), sum(e['units'] for e in sub), 100*sum(e['units'] for e in sub)/len(sub), ('%+.2f' % mean(cv)) if cv else 'n/a', len(cv)))
    cv = [(e['age_fp'], clvpts(e)) for e in s if clvpts(e) is not None]
    if len(cv) > 5:
        mx = mean(a for a, b in cv); my = mean(b for a, b in cv)
        sxx = sum((a-mx)**2 for a, b in cv); sxy = sum((a-mx)*(b-my) for a, b in cv)
        pr('     slope clv_pts per hour of price age = %+.3f (n=%d)' % (60*sxy/sxx if sxx else float('nan'), len(cv)))

txt = '\n'.join(out)
open(os.path.join(HERE, 'out_clv.txt'), 'w', encoding='utf-8').write(txt)
print(txt)
