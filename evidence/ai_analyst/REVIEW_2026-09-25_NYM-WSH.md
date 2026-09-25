# Opus review of the critic report for NYM-WSH-2026-09-25-1 (2026-09-25)

Report under review: `NYM-WSH-2026-09-25-1_20260925T152914Z_analyst_report.json`.
The report is left exactly as written. This note is appended beside it.

**Verdict: REVIEW FAILED. Do not treat the finding as evidence.**

What passed:
- Every claim cites an evidence id or a model-input path.
- `validate_hard_limits` ran. There is no invented probability, no threshold
  key and no write to a published record.
- `contribution_kind` is `session_assisted`, and the report is logged apart
  from the shadow artifact.

What failed, with each point checked against the report's own sources:
1. **Wrong numeric claim.** `case_against` point 4 says this pick's score
   (0.0964) was "one of the smaller scores" on the slate, and compares it
   with 0.0842 and 0.0508. It is the largest of the three (source:
   `2026-09-25_20260925T143000Z_moneyline-run_line.json`).
2. **The central challenge rests on an unverified identity.** The finding
   links the home starter to DJ Herz, activated from the 60-day injured list
   (`mlb_news:943391`), yet says itself that the model carries no pitcher
   name. The "innings-limited" reading leans on `home_sp_recent_starts=3` and
   `home_sp_recent_ip_per_start=5.0`. Those look like a fixed recent window:
   `home_sp_recent_era` (3.6) equals the season ERA exactly, and the
   season's IP per start is already 4.881. They are not evidence of a
   managed workload.

What it means: the checks on the report's format work, but nothing checks
that the facts in its text are true. Before a critic finding counts, every
numeric or ranking statement in `case_against` or `challenged_assumption`
must be recomputed from the cited source by code. A challenge built on an
UNVERIFIED link may be offered only as an alternate scenario, never as the
reason for RECALCULATION_REQUESTED.
