import json,collections,glob
def load(f): return [json.loads(l) for l in open(f,encoding='utf-8') if l.strip()]
for f in ['cards_v1','cards_v1_shadow','cards_v2','cards_v2_shadow_a','cards_v2_shadow_c','cards_v2_shadow_e','cards_nfl_v1','cards_mma_v1']:
    rows=load(f'data/{f}.jsonl')
    pubs=[r for r in rows if r['kind']=='card_published']
    sets=[r for r in rows if r['kind']=='card_settled']
    other=collections.Counter(r['kind'] for r in rows)
    print('==',f,dict(other))
    print('  pub dates', sorted(set(r['date'] for r in pubs))[:3],'..',sorted(set(r['date'] for r in pubs))[-3:], 'ndates',len(set(r['date'] for r in pubs)),'rules',collections.Counter(r.get('rule') for r in pubs))
    for s in sets:
        tot=lambda k: s.get(k)
        print('  set',s['date'],s.get('settled_utc','')[:16],'pass',s.get('settlement_pass'),'W-L-P-V-U',s.get('wins'),s.get('losses'),s.get('pushes'),s.get('voids'),s.get('unresolved'),'u',s.get('profit_units'),
              '| prop',s.get('prop_wins'),s.get('prop_losses'),s.get('prop_profit_units'),'| tot',s.get('total_wins'),s.get('total_losses'),s.get('total_profit_units'), 'ngraded',len(s.get('graded') or s.get('picks') or []))
