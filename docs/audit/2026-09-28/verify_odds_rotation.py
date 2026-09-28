"""P2: prove every odds_multibook rotation on origin preserved the logical
store byte-for-byte. logical(commit) = decompressed segments (sorted) + hot.
For each rotation commit C: logical(C^) must be a byte PREFIX of logical(C)
(rotation moves bytes, the same slot may append new rows after them).
End to end: logical(8aea5e90, the last pre-hotfix commit) must be a prefix of
logical(origin tip)."""
import gzip, hashlib, subprocess, json

HOT = "data/processed/odds_multibook.jsonl"
SEGDIR = "data/processed/archive/odds_multibook/"

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, check=True).stdout

def logical(rev):
    names = [l for l in git("ls-tree", "--name-only", rev, SEGDIR).decode().split("\n") if l.endswith(".jsonl.gz")]
    names.sort()
    segs = [gzip.decompress(git("show", f"{rev}:{n}")) for n in names]
    hot = git("show", f"{rev}:{HOT}")
    return names, b"".join(segs), hot

def rows(b):
    return b.count(b"\n")

def check(parent, child, label, per_rotation=True):
    pn, ps, ph = logical(parent)
    cn, cs, ch = logical(child)
    pl, cl = ps + ph, cs + ch
    new = [n for n in cn if n not in pn]
    ok = cl.startswith(pl)
    # every line in the new segment(s) must come from the parent's hot file prefix
    newseg = b"".join(gzip.decompress(git("show", f"{child}:{n}")) for n in new)
    moved_ok = ph.startswith(newseg)
    print(f"{label}: parent {parent[:8]} logical {len(pl):,} B / {rows(pl):,} rows -> child {child[:8]} logical {len(cl):,} B / {rows(cl):,} rows")
    print(f"   new segment(s) {new}: {len(newseg):,} B, {rows(newseg):,} rows, taken from the start of the parent's hot file: {moved_ok}")
    print(f"   hot {len(ph):,} -> {len(ch):,} B; parent logical is a byte-prefix of child logical: {ok}; appended after: {len(cl)-len(pl):,} B")
    return ok and (moved_ok or not per_rotation)

R = "origin/claude/sports-betting-analysis-review-g1o0co"
results = []
for c, label in (("e6e387e0", "0006 rotation"), ("1781f000", "0007 rotation"), ("1fed5255", "0008 rotation")):
    results.append(check(git("rev-parse", f"{c}^").decode().strip(), git("rev-parse", c).decode().strip(), label))
tip = git("rev-parse", R).decode().strip()
results.append(check(git("rev-parse", "8aea5e90").decode().strip(), tip, "END-TO-END 8aea5e90 -> origin tip (prefix check only; later segments also hold rows appended after 8aea5e90)", per_rotation=False))
tn, ts, th = logical(tip)
bad = 0
for line in (ts + th).split(b"\n"):
    if line.strip():
        try: json.loads(line)
        except ValueError: bad += 1
print(f"origin tip: {len(tn)} segments, hot {len(th):,} B, logical rows {rows(ts+th):,}, unparseable lines {bad}")
print("ALL PRESERVED" if all(results) else "PRESERVATION FAILURE")
