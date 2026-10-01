import json,sys,collections,glob
for f in sorted(glob.glob('data/*.jsonl'))+sorted(glob.glob('data/mvs/*.jsonl')):
    rows=[json.loads(l) for l in open(f,encoding='utf-8') if l.strip()]
    kinds=collections.Counter(r.get('kind') for r in rows)
    print('==',f,len(rows),dict(kinds))
    seen=set()
    for r in rows:
        k=r.get('kind')
        if k in seen: continue
        seen.add(k)
        print('  kind',k,'keys:',sorted(r.keys()))
        for lk,v in r.items():
            if isinstance(v,list) and v and isinstance(v[0],dict):
                print('    list',lk,len(v),'item keys:',sorted(v[0].keys()))
