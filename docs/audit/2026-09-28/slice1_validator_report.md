# Slice 1 validator report (independent, adversarial), 2026-09-28

Validator: a separate Sonnet agent (opus-validator role) working read-only
against worktree commit `753c2621` with its own scripts, never the
implementer's simulation. Verdict: **SHIP**. Condensed from its report; the
scripts are in the session scratchpad (`validator/phase1_before.py` ..
`phase10_guard_check.py`).

## Acceptance A-H

- A row count: independent parse 33,252 before; 32,859 archived + 393 hot = 33,252 after. PASS.
- B bytes and identities: an independent re-run of `rotate()` on a fresh copy of the
  origin bytes reproduced the committed hot file and the committed segment
  byte-for-byte (compressed and decompressed); `sha256(concat) ==
  1ccee141...`. PASS.
- C reader parity, before vs after, programmatic diff: `load_decisions`
  (33,193), `_load_existing_decision_keys` (33,193), `ensure_genesis` (same
  row, appends nothing), `slate_due.last_decision_utc`,
  `research_readiness._decision_rows` (33,252), `test_tier_ladder._load_plays`,
  `bridge.verify()` (full dict, also with a real copy of forward_ledger.jsonl).
  PASS.
- D tamper detection: a flipped row inside the segment reported at logical
  line 5000; inside the hot file at 33,000. PASS.
- E append after rotation: `prev_hash` equals the pre-rotation last
  `row_hash` (`ccc4b1de...`); verify 33,253. PASS.
- F idempotence: same `now` at 60 MiB no-op; same `now` with the threshold
  forced open still a no-op on the date cutoff; +6 days with three appended
  rows produced `0002_2026-09-27_2026-10-01.jsonl.gz`, verify 33,255,
  `last_hash` falls back to 0002 with an emptied hot file. PASS.
- G interrupted rotation: mocked proof failure and mocked hot-file replace
  failure both leave the store untouched with no orphans; the hand-built
  duplicate-prefix state is reported by `verify()` at line 32,860 and the
  next `rotate()` refuses with `ESCALATE duplicate prefix`; the CLI exits 2.
  PASS.
- H headroom: heaviest day ever 11.7 MB (2026-09-09); worst case 60 MiB
  threshold plus one heaviest-day slot = 74.7 MB (71.2 MiB) against the
  104.9 MB limit. PASS.

## Attacks

Torn last line before rotation (untouched), empty hot file, hot row without
`row_hash`, two rotations in one day, a numbering gap (0001 + 0003 -> next is
0004), a malformed segment name (ignored), `iter_lines(since=...)` on the wide
0001 span (no caller passes `since` for this store), rebase rehearsal in both
directions (clean, chain verifies at 33,255), runner dry run on an unrotated
copy (`rotated 33251 row(s)`, hot 3,130 bytes) and on the rotated layout
(no-op), git hygiene (segment tracked, `*.tmp` ignored, hot blob 1,153,025
bytes, `bash -n` clean), reader audit (no plain `open()` of the ledger left),
test-write protection (real ledger and archive blocked). All PASS.

## Findings

1. Pre-existing, not introduced: `HashChainLedger.append()` has no torn-line
   healing; a torn tail followed by an append merges two rows on one line and
   `read()`/`verify()` raise `JSONDecodeError` instead of returning a clean
   failure. Follow-up.
2. Introduced by 753c2621, fixed in the follow-up commit before push:
   `last_hash()` read the hot file in text mode (splits on a bare CR) while
   `read()`/`verify()` split on newline bytes only. Both now read bytes; a
   test pins the agreement.
3. CRLF exposure: rotating a CRLF working copy would bake CR bytes into an
   immutable segment (the proof is self-referential). `.gitattributes`
   `evidence/*.jsonl text eol=lf` protects the git boundary; the live-file
   window between a CRLF-producing local write and the next add remains a
   Windows-only hazard. Runners never write CR.
4. Full suite (12 shards, `python -m unittest`): zero new regressions; the
   two `test_daily_bootstrap` seed errors are 30 s subprocess timeouts that
   pass when run alone.
5. Timing on the 104 MB file: phase 1 + 2 wall 12.8 s, peak working set
   1,407.7 MB (single process).
