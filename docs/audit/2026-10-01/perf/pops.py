"""Named, non-pooled populations used by analysis.py / clv_audit.py."""
from common import *

def staked(es): return [e for e in es if e['result'] in ('WIN', 'LOSS')]

def populations(cards):
    P = {}
    def add(name, pred): P[name] = [e for e in cards if pred(e)]
    V1G = lambda e: e['ledger'] == 'cards_v1.jsonl' and e['kind'] == 'game'
    add('V1pub games pick', lambda e: V1G(e) and e['entry_class'] == 'pick')
    add('V1pub games SPLIT', lambda e: V1G(e) and e['entry_class'] != 'pick')
    add('V1pub props hits', lambda e: e['ledger'] == 'cards_v1.jsonl' and e['market'] == 'batter_hits')
    add('V1pub props TB', lambda e: e['ledger'] == 'cards_v1.jsonl' and e['market'] == 'batter_total_bases')
    add('V1shadow games pick', lambda e: e['ledger'] == 'cards_v1_shadow.jsonl' and e['kind'] == 'game' and e['entry_class'] == 'pick')
    add('V1shadow props hits', lambda e: e['ledger'] == 'cards_v1_shadow.jsonl' and e['market'] == 'batter_hits')
    add('V1shadow props TB', lambda e: e['ledger'] == 'cards_v1_shadow.jsonl' and e['market'] == 'batter_total_bases')
    V2 = lambda e: e['ledger'] == 'cards_v2.jsonl'
    add('V2pub MAIN picks', lambda e: V2(e) and e['entry_class'] == 'pick' and e.get('price_class') == 'MAIN')
    add('V2pub PLUS picks', lambda e: V2(e) and e['entry_class'] == 'pick' and e.get('price_class') == 'PLUS_MONEY')
    add('V2pub fills', lambda e: V2(e) and e['entry_class'] == 'fill')
    add('V2pub withdrawn', lambda e: V2(e) and e['entry_class'] == 'withdrawn')
    for x, nm in (('a', 'A'), ('c', 'C'), ('e', 'E')):
        fn = 'cards_v2_shadow_%s.jsonl' % x
        add('V2shadow%s picks' % nm, lambda e, fn=fn: e['ledger'] == fn and e['entry_class'] == 'pick')
        add('V2shadow%s fills' % nm, lambda e, fn=fn: e['ledger'] == fn and e['entry_class'] == 'fill')
    add('NFL_CARD_V1', lambda e: e['rule'] == 'NFL_CARD_V1')
    add('NFL_CARD_V2', lambda e: e['rule'] == 'NFL_CARD_V2')
    return P
