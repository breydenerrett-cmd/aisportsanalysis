import json
def load(f): return [json.loads(l) for l in open(f,encoding='utf-8') if l.strip()]
v1=load('data/cards_v1.jsonl')
s=[r for r in v1 if r['kind']=='card_settled'][-1]
pub=[r for r in v1 if r.get('row_hash')==s['published_row_hash']][0]
print('V1 pub keys',sorted(pub.keys()), 'calibrated',pub.get('calibrated'),'calib',pub.get('calibration'))
p=pub['picks'][0]; print(json.dumps({k:v for k,v in p.items() if k not in('why',)},default=str)[:1500])
print(json.dumps(pub.get('prop_picks',[{}])[0],default=str)[:1500])
print('settled pick',s['picks'][0]); print('settled prop',s['prop_picks'][0])
v2=load('data/cards_v2.jsonl'); s2=[r for r in v2 if r['kind']=='card_settled'][0]
g=s2['graded'][0]; print('V2 graded',json.dumps({k:v for k,v in g.items() if k not in('why',)},default=str)[:2500])
pv=[r for r in v2 if r['kind']=='card_published'][-1]; print('V2 params',pv['params'])
nfl=load('data/cards_nfl_v1.jsonl'); print('NFL', json.dumps([ {k:v for k,v in p.items() if k!='why'} for p in nfl[0]['picks']],default=str)[:1200])
lc=load('data/live_candidates_v1.jsonl'); print('LC',lc[0]); print('LS',[r for r in lc if r['kind']=='live_settled'][0])
d=load('data/mvs/B_HITS_decisions.jsonl')[0]; print('MVS dec',d); print('MVS set',load('data/mvs/B_HITS_settled.jsonl')[0])
print('MVS C', load('data/mvs/C_RUN_LINE_decisions.jsonl')[0])
