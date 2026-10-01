"""Shared loaders for the read-only performance audit.
Data exported from origin/claude/sports-betting-analysis-review-g1o0co into ./data
via git show; origin src + odds store exported into ./repo via git archive."""
import json, os, glob, math, collections
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, 'data')

def load(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]

def dec(price):
    if price is None: return None
    p = float(price)
    if p >= 100: return 1 + p/100.0
    if p <= -100: return 1 + 100.0/(-p)
    return None

def be(price):
    d = dec(price); return 1/d if d else None

def dec_to_american(d):
    if d is None: return None
    return (d-1)*100 if d >= 2 else -100/(d-1)

def band(price):
    p = float(price)
    if p <= -160: return '<=-160'
    if p <= -100: return '-159..-100'
    if p <= 250: return '+100..+250'
    return '>+250'

def ts(s):
    if s is None or isinstance(s, (int, float)): return None
    try:
        t = datetime.fromisoformat(str(s).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

def latest_settled(rows, kind='card_settled'):
    out = {}
    for r in rows:
        if r.get('kind') == kind:
            out[r.get('date')] = r
    return out

def _pk(p):
    if p.get('sport') == 'nfl': return (str(p.get('game_id')),)
    g = str(p.get('game_id')) if p.get('sport') else str(p.get('game_pk'))
    return (g, p.get('market'))

def _ppk(p): return (str(p.get('game_pk')), p.get('player'))
def _tpk(p): return (str(p.get('game_pk')),)

def v1_entries(fname, vis):
    rows = load(os.path.join(D, fname))
    pubs = {r['row_hash']: r for r in rows if r['kind'] == 'card_published'}
    corr = [r for r in rows if r['kind'] == 'card_pick_correction']
    assert not corr, 'corrections present'
    out = []
    for date, s in sorted(latest_settled(rows).items()):
        pub = pubs.get(s.get('published_row_hash')) or {}
        for scope, kf in (('picks', _pk), ('prop_picks', _ppk), ('total_picks', _tpk)):
            idx = {kf(p): p for p in (pub.get(scope) or [])}
            for g in s.get(scope) or []:
                e = dict(idx.get(kf(g)) or {})
                joined = bool(e)
                e.update(g)
                sport = e.get('sport') or 'mlb'
                if scope == 'prop_picks':
                    rule = 'DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1'
                    p_our = e.get('probability'); kind = 'prop'
                elif scope == 'total_picks':
                    rule = 'DAILY_CARD_TOTAL_MARKET_SIDE_MODEL_AGREEMENT_V1'
                    p_our = e.get('model_probability'); kind = 'total'
                else:
                    rule = pub.get('rule'); p_our = e.get('model_probability'); kind = 'game'
                ec = 'fill(SPLIT)' if e.get('label') == 'SPLIT' else 'pick'
                out.append(dict(ledger=fname, vis=vis, rule=rule, sport=sport, kind=kind,
                    market=e.get('market'), entry_class=ec, date=date, price=e.get('price'),
                    result=e.get('result'), units=e.get('profit_units') or 0.0,
                    p_our=p_our, p_our_raw=p_our, p_mkt=e.get('market_probability'),
                    observed_utc=e.get('observed_utc'), first_pitch_utc=e.get('first_pitch_utc'),
                    locked_at=e.get('locked_at'), event_id=e.get('event_id'), game_pk=e.get('game_pk'),
                    game_id=e.get('game_id'), side=e.get('side'), line=e.get('line'), player=e.get('player'),
                    team=e.get('team'), label=e.get('label'), books=e.get('books'), joined=joined,
                    away_score=e.get('away_score'), home_score=e.get('home_score'),
                    reason=e.get('reason'), raw=e))
    return out

def v2_entries(fname, vis):
    rows = load(os.path.join(D, fname))
    out = []
    for date, s in sorted(latest_settled(rows).items()):
        for e in s.get('graded') or []:
            kind = 'prop' if e.get('kind') == 'prop' else 'game'
            ec = 'withdrawn' if e.get('withdrawn') else (e.get('entry_class') or '?')
            out.append(dict(ledger=fname, vis=vis, rule=s.get('rule'), sport=e.get('sport') or 'mlb',
                kind=kind, market=e.get('market'), entry_class=ec, date=date, price=e.get('price'),
                result=e.get('result'), units=e.get('profit_units') or 0.0,
                p_our=e.get('our_probability_used'), p_our_raw=e.get('our_probability'),
                p_mkt=e.get('market_probability'), price_class=e.get('price_class'),
                observed_utc=e.get('observed_utc'), first_pitch_utc=e.get('first_pitch_utc'),
                locked_at=e.get('locked_at'), event_id=e.get('event_id'), game_pk=e.get('game_pk'),
                game_id=e.get('game_id'), side=e.get('side'), line=e.get('line'), player=e.get('player'),
                team=e.get('team'), label=e.get('label'), books=e.get('books'), joined=True,
                fill_quote_age_seconds=e.get('fill_quote_age_seconds'),
                away_score=e.get('away_score'), home_score=e.get('home_score'),
                reason=e.get('reason') or e.get('void_reason'), raw=e))
    return out

def card_entries():
    out = []
    out += v1_entries('cards_v1.jsonl', 'PUBLIC')
    out += v1_entries('cards_v1_shadow.jsonl', 'SHADOW')
    out += v2_entries('cards_v2.jsonl', 'PUBLIC')
    for x in 'ace':
        out += v2_entries('cards_v2_shadow_%s.jsonl' % x, 'SHADOW')
    nfl = v1_entries('cards_nfl_v1.jsonl', 'PUBLIC')
    for e in nfl: e['sport'] = 'nfl'
    out += nfl
    return out

def live_entries():
    rows = load(os.path.join(D, 'live_candidates_v1.jsonl'))
    cands = [r for r in rows if r['kind'] == 'live_candidate']
    sets = {}
    for r in rows:
        if r['kind'] == 'live_settled':
            sets[(r['rule_id'], str(r['game_id']), r['side'])] = r
    out = []
    for c in cands:
        s = sets.get((c['rule_id'], str(c['game_id']), c['side'])) or {}
        rule = c['rule_id'] + (('@' + c['rule_version']) if c.get('rule_version') else '')
        ec = 'cand(elig)' if c.get('customer_eligible') else 'cand(not_elig)'
        out.append(dict(ledger='live_candidates_v1.jsonl', vis='SHADOW', rule=rule, sport=c.get('sport'),
            kind='live', market='moneyline_inplay', entry_class=ec, date=c['date'], price=c.get('price'),
            result=s.get('result') or 'UNSETTLED', units=s.get('profit_units') or 0.0,
            p_our=None, p_our_raw=None, p_mkt=None, status=c.get('status'), raw=c))
    return out

def mvs_entries():
    out = []
    for f in sorted(glob.glob(os.path.join(D, 'mvs', '*_decisions.jsonl'))):
        decs = load(f)
        sf = f.replace('_decisions', '_settled')
        sets = {r['decision_key']: r for r in load(sf)} if os.path.exists(sf) else {}
        for d in decs:
            s = sets.get(d['decision_key']) or {}
            out.append(dict(ledger='mlb_value_shadow_v1/' + os.path.basename(f), vis='SHADOW',
                rule=d['rule_id'], sport='mlb', kind='prop' if d.get('player') else 'game',
                market=d.get('market'), entry_class='decision', date=d['date'], price=d.get('price'),
                result=s.get('result') or 'UNSETTLED', units=s.get('profit_units') or 0.0,
                p_our=d.get('fair_probability'), p_our_raw=d.get('fair_probability'), p_mkt=None,
                reason=s.get('reason'), raw=d))
    return out

def paper_entries():
    import sys
    sys.path.insert(0, os.path.join(HERE, 'repo'))
    from src.report.engine_bridge import system_class
    out = []
    for f in sorted(glob.glob(os.path.join(D, 'pa', '*.jsonl'))):
        rows = load(f)
        seen = {}
        for r in rows:
            seen[r.get('bet_id')] = r
        for r in seen.values():
            oc = (r.get('outcome') or '').upper()
            res = oc if oc in ('WIN', 'LOSS', 'PUSH', 'VOID') else (oc or 'UNSETTLED')
            out.append(dict(ledger='paper_accounts/' + os.path.basename(f), vis=system_class(r.get('system_id')),
                rule=r.get('system_id'), sport='mlb', kind='paper', market=r.get('market_key'),
                entry_class='fill(paper)', date=r.get('day'), price=r.get('price_american'),
                result=res, units=r.get('profit_units') or 0.0, p_our=None, p_our_raw=None, p_mkt=None,
                side=r.get('side'), line=r.get('line'), raw=r))
    return out

def mkt_label(e):
    m = e.get('market')
    if m in ('run_line', 'spread', 'spreads'): return 'run_line/spread'
    if m in ('total', 'totals'): return 'total'
    return m
