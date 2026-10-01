"""GOAL 1: one row per (rule, sport, market, visibility, entry class, price band)."""
import collections, sys, os
from common import *

def summarize(es):
    W = sum(e['result'] == 'WIN' for e in es); L = sum(e['result'] == 'LOSS' for e in es)
    P = sum(e['result'] == 'PUSH' for e in es); V = sum(e['result'] == 'VOID' for e in es)
    U = sum(e['result'] in ('UNRESOLVED', 'UNSETTLED') for e in es)
    st = [e for e in es if e['result'] in ('WIN', 'LOSS')]
    units = sum(e['units'] for e in st)
    ds = [dec(e['price']) for e in st if dec(e['price'])]
    md = sum(ds)/len(ds) if ds else None
    bes = [be(e['price']) for e in st if be(e['price'])]
    pm = [e['p_mkt'] for e in st if e.get('p_mkt') is not None]
    po = [e['p_our'] for e in st if e.get('p_our') is not None]
    dates = sorted(e['date'] for e in es if e.get('date'))
    return dict(n=len(es), W=W, L=L, P=P, V=V, U=U, units=units,
        roi=(units/len(st)*100 if st else None), mprice=dec_to_american(md) if md else None,
        mbe=(sum(bes)/len(bes) if bes else None), mpm=(sum(pm)/len(pm) if pm else None),
        mpo=(sum(po)/len(po) if po else None), wr=(W/len(st) if st else None),
        d0=dates[0] if dates else '', d1=dates[-1] if dates else '')

def f(x, fmt):
    return '' if x is None else format(x, fmt)

ORDER = ['<=-160', '-159..-100', '+100..+250', '>+250', 'ALL']
HDR = ('RULE'.ljust(48) + ' SP   ' + 'MARKET'.ljust(19) + ' ' + 'VIS'.ljust(9) + ' ' + 'ENTRY'.ljust(14) + ' ' +
       'BAND'.ljust(10) + ' ' + 'DATES'.ljust(11) + '    N    W    L   P   V   U    UNITS    ROI%    mPx   mBE  mMkt  mOur    WR')

def row(k, s):
    rule, sp, mk, vis, ec, bd = k
    dr = (s['d0'][5:] + '..' + s['d1'][5:]) if s['d0'] else ''
    return (str(rule)[:48].ljust(48) + ' ' + str(sp)[:4].ljust(4) + ' ' + str(mk)[:19].ljust(19) + ' ' + vis[:9].ljust(9) + ' ' +
            ec[:14].ljust(14) + ' ' + bd.ljust(10) + ' ' + dr.ljust(11) +
            f" {s['n']:>4} {s['W']:>4} {s['L']:>4} {s['P']:>3} {s['V']:>3} {s['U']:>3} {s['units']:>8.2f} {f(s['roi'],'.1f'):>7}"
            f" {f(s['mprice'],'.0f'):>6} {f(s['mbe'],'.3f'):>5} {f(s['mpm'],'.3f'):>5} {f(s['mpo'],'.3f'):>5} {f(s['wr'],'.3f'):>5}")

def table(entries, keyfn, title, out, with_bands=True):
    g = collections.defaultdict(list)
    for e in entries:
        g[keyfn(e) + ('ALL',)].append(e)
        if with_bands and e.get('price') is not None:
            g[keyfn(e) + (band(e['price']),)].append(e)
    out.append('### ' + title)
    out.append(HDR)
    for k in sorted(g, key=lambda k: tuple(str(x) for x in k[:-1]) + (ORDER.index(k[-1]),)):
        if k[-1] != 'ALL' and len({band(e['price']) for e in g[k[:-1] + ('ALL',)] if e.get('price') is not None}) == 1:
            continue   # single-band group: the ALL row already is that band
        out.append(row(k, summarize(g[k])))
    out.append('')

if __name__ == '__main__':
    cards = card_entries(); live = live_entries(); mvs = mvs_entries(); pa = paper_entries()
    out = []
    K = lambda e: (e['rule'], e['sport'], mkt_label(e), e['vis'], e['entry_class'])
    table(cards, K, 'CARD LEDGERS (newest settled row per date; ALL row then each price band present)', out)
    table(mvs + live, K, 'MLB VALUE SHADOW + LIVE CANDIDATES', out)
    table(pa, lambda e: (e['rule'], e['sport'], mkt_label(e), e['vis'], e['entry_class']), 'PAPER ACCOUNTS (engine systems), newest row per bet_id', out)
    mma = load(os.path.join(D, 'cards_mma_v1.jsonl'))
    lastpub = {}
    for r in mma:
        if r['kind'] == 'card_published': lastpub[r['date']] = r
    out.append('MMA cards_mma_v1.jsonl: published only, zero card_settled rows: ' +
               '; '.join('%s %d picks rule %s' % (d, len(r.get('picks') or []), r.get('rule')) for d, r in sorted(lastpub.items())))
    txt = '\n'.join(out)
    open(os.path.join(HERE, 'out_record_table.txt'), 'w', encoding='utf-8').write(txt)
    print(txt)
