# Map — orchestration & ops

Subsystem: the standing autonomous-research/build machinery — nightly/hourly
cycle contract, worker roles (Fable/Opus/Sonnet/deterministic), the
worktree store-completeness rule, pinned reads, the adversarial-review
gate, budget/credit governors, and what actually runs where (GitHub
Actions vs. an interactive model session vs. Fly). Written read-only,
2026-09-03, against `claude/sports-betting-analysis-review-g1o0co` at
`bb755a0`.

Method note up front: almost everything the vision calls "the standing
autonomous research department" exists today as **habit encoded in
markdown**, not as **code a scheduler runs unattended**. The distinction
matters more here than in any other subsystem, because the owner vision
explicitly asks for a factory that runs without a human watching, and the
honest answer is that most of the loop still needs an interactive Claude
session in the loop to fire the scripts and interpret their output.

---

## 1. Worker roles (Fable / Opus / Sonnet / deterministic)

**EXISTS (partial, as prompts not as a dispatcher):**
- `.claude/agents/*.md` — six Opus subagent role files, each following the
  same OBJECTIVE/WHY/INPUTS/BOUNDARIES/DELIVERABLE/ACCEPTANCE/EVIDENCE
  contract: `opus-builder.md` (general implementation), `opus-data.md`
  (data/collection, credit-aware), `opus-product.md` (Analyzer/report
  surface), `opus-redteam.md` (adversarial bug-hunting with reproductions),
  `opus-research.md` (pre-registration/measurement under frozen evidence
  rules), `opus-validator.md` (adversarial verification of another
  worker's deliverable against its own acceptance criteria — "your job is
  to try to FAIL it"). All six pin `model: opus` in frontmatter and all
  six repeat the same non-negotiables verbatim: never fabricate a value,
  no bet-placement capability ever, Ranker Engine 2 stays gated, 2025
  tuning-only / 2026-01-01..08-27 sealed, run `test_fast.sh` while
  iterating and `test_parallel.py` before declaring done, never the raw
  `unittest discover`, don't commit/push unless told to.
- These are genuinely usable Claude Code subagent definitions (this
  session's own harness reads `.claude/agents/`), so "Opus on
  implementations/hypotheses" — the vision's phrase — is real:
  `opus-builder`/`opus-data`/`opus-product` are implementation workers,
  `opus-research` is the hypothesis worker.

**CLAIMED-BUT-ABSENT:**
- No `fable-*.md` or `sonnet-*.md` agent file exists anywhere in the repo
  (`find .claude -type f` returns only the six `opus-*.md` files plus one
  skill). "Sonnet on implementations/hypotheses" in the vision is
  inverted from what's actually configured: the checked-in worker roles
  are all Opus. Every mention of "Sonnet implementation lanes" or "Fable
  orchestrating" (`docs/ORCHESTRATION_DAY_2026-09-02.md:3-8`,
  `docs/COMMAND_CENTER.md:191-196`) is a narrative description of what a
  *particular session* did that day, not a role definition a scheduler can
  invoke. There is no file that says "when the orchestrator needs a
  builder, spawn Sonnet"; the actual spawnable roster (`.claude/agents/`)
  is Opus-only. If the true intended split is Opus=methodology/review and
  Sonnet=implementation, the agent files as written contradict that (they
  are execution-worker prompts, tagged Opus).
- "Deterministic infrastructure evaluating millions of decisions" exists
  only at the scale already documented for Evolab (`src/evolab/`,
  8,811-genome Phase 2B sweep — see the compute-scale map for that
  subsystem) and the test suite (~3,000 tests, `scripts/test_parallel.py`).
  Nothing here is millions of decisions; that's a difference of ~2-3
  orders of magnitude from the vision's stated scale, worth naming
  explicitly rather than letting "deterministic infra" imply parity.
- No orchestrator *dispatch* mechanism exists in-repo — no queue, no
  "assign task to worker N" code. Every lane described in
  `docs/ORCHESTRATION_DAY_2026-09-02.md` (L0–L24) was a human/session
  narrating "I delegated this to a worktree," not a system invoking
  workers on its own. `mcp__ccd_session__spawn_task` (available to this
  session via tooling, not repo code) is the closest thing to a dispatch
  primitive, but it is a suggestion queued for a *human* to click, not
  autonomous dispatch.

**BOOST vs REPLACE:** BOOST — the Opus agent contract shape (OBJECTIVE/
WHY/INPUTS/BOUNDARIES/DELIVERABLE/ACCEPTANCE/EVIDENCE, shared hard rules)
is well-designed and worth keeping as the template; it just needs
Sonnet/Fable variants added and a real dispatcher (even a simple queue
file + session convention) to stop being six prompts that a human reads
and manually assigns.

---

## 2. Nightly/hourly cycle contract — what is code vs. what is a claim

### 2a. Hourly forward capture

**EXISTS, and now split across two implementations:**
- `scripts/forward_capture.sh` (139 lines) — the original in-session loop:
  `watch` (free roster/lineup/transaction poll) → `umpirewatch.py` (free
  umpire-crew poll, added 2026-09-02, L11) → `dense` (credit-gated odds
  grid with its own internal 45-minute/4-capture loop and T-25 F5 close
  pass) → `capture_extras.sh` (weather, credit-balance log, gated prop
  prices) → one shared-lock (`/tmp/linehound_git.lock` via `flock -w 300`)
  commit-and-push with `git fetch && git pull --rebase --autostash` before
  push, explicit staged paths, `ESCALATE:` lines grepped through verbatim.
  Meant to be fired once an hour by an interactive session/Routine, per
  `docs/RUNBOOK.md:7`.
- `scripts/capture_slot.sh` (104 lines, added 2026-09-02 as L25) — the
  externalized version: same watch/umpire polls, but exactly **one** dense
  capture (`--captures 1 --interval 0`, no in-process sleep — verified by
  `tests/test_dense.py`'s `test_a_single_slot_run_captures_once_and_never_sleeps`),
  then prop-listing, then extras, then the same lock/commit/rebase/push
  sequence. Designed to be invoked every 15 minutes by an external
  scheduler instead of looping internally for 45 minutes inside one
  process — motivated explicitly by "five interactive-session container
  restarts on 2026-09-02 killed `forward_capture.sh` mid-`dense` run each
  time" (`docs/CAPTURE_EXTERNALIZATION.md:1-4`).
- `.github/workflows/forward-capture.yml` — `cron: "*/15 * * * *"` +
  `workflow_dispatch`, `concurrency: group: forward-capture` (serializes
  against itself), `permissions: contents: write, actions: write`, checks
  out `ref: claude/sports-betting-analysis-review-g1o0co` explicitly
  (fact below explains why), sets a bot git identity, runs
  `capture_slot.sh` with `ODDS_API_KEY` from `secrets.ODDS_API_KEY`, then
  — only if this run's HEAD commit subject starts with "Forward capture
  slot" **and** the UTC minute is in the 00-14 band (first slot of the
  hour) — fires `deploy-staging.yml` via the Actions API so staging's
  baked-in data stays roughly hourly-fresh without a second credential.

**PARTIAL / CLAIMED-BUT-ABSENT — the externalized path is not confirmed
running:**
- The repository's **default branch is still the orphan
  `claude/cowork-session-migration-tn3sx2`**, which shares no git history
  with the working line (`git remote show origin` → `HEAD branch:
  claude/cowork-session-migration-tn3sx2`; confirmed live during this
  read). GitHub only fires `schedule:` triggers from a repo's default
  branch. `docs/CAPTURE_EXTERNALIZATION.md`'s own "Default-branch
  constraint" section (added at orchestrator review) says this outright:
  the workflow "will not be scheduled until" the owner repoints the
  default branch or the file is separately pushed to the orphan branch —
  neither has happened (`docs/ORCHESTRATION_DAY_2026-09-02.md`'s "STILL
  BLOCKED (owner-only)" item 1 names this exact gap as of end-of-day
  2026-09-02, unresolved at the time of this read).
- Consistent with that: `git log --author="forward-capture-bot"` (the git
  identity `forward-capture.yml` configures) returns **zero commits** in
  this checkout, while every recent "Forward capture HH:MMZ" commit in
  `git log` is authored `Claude <noreply@anthropic.com>` — the in-session
  identity, not the Actions bot's. The most recent commit at read time,
  `bb755a0 "Forward capture 00:03Z"`, is an in-session commit, not an
  Actions one. **The GitHub Actions capture path is merged and testable
  in isolation, but there is no evidence in this checkout's history that
  it has ever actually fired on schedule.** The hourly cadence the
  vision needs is, right now, still riding on an interactive
  session/Routine calling `forward_capture.sh`/`capture_slot.sh` by hand
  or via a Routine trigger — exactly the single point of failure L25 was
  written to remove.
- Owner action still outstanding per `docs/CAPTURE_EXTERNALIZATION.md`'s
  "OWNER DECISIONS" section: `ODDS_API_KEY` has not been confirmed added
  as a **repository** Actions secret (distinct from the Fly app's
  secrets, which do not include it — verified separately in that doc,
  fact 2). Without it, `dense`/`prop_listing`/`prop_prices` all no-op
  ("not configured") inside a real run, which would look like a
  successful but empty capture — silent, per the same "silence is not
  success" principle `docs/RUNBOOK.md:31` states for stores that never
  get created.
- Cutover sequence step 4 in that doc ("only after step 3's commit is
  confirmed: disable the in-session hourly forward-capture trigger") has
  therefore not been reached — by the doc's own sequencing, step 3
  (confirm one successful Actions commit) hasn't happened yet, so step 4
  can't have either. **Two writers may currently both be live** (the
  Actions workflow, if its schedule ever does fire post-branch-repoint,
  plus whatever in-session Routine is still calling `forward_capture.sh`)
  — the shared-lock design tolerates concurrent writers on one host but
  the lock (`flock` on a local `/tmp` path) is **not cross-host**, a gap
  `docs/CAPTURE_EXTERNALIZATION.md`'s own options table names for Fly
  (Option B) without equally flagging it for the eventual two-writer case
  between an Actions runner and an interactive session, since Actions
  runners are ephemeral and each run's `git pull --rebase` is the only
  thing actually serializing the two paths (JSONL-append + rebase-before-
  push, not a distributed lock).

**BOOST vs REPLACE:** BOOST. The design (Option A analysis in
`CAPTURE_EXTERNALIZATION.md`) is sound and the code is real; what's
missing is two owner-only actions (repo secret, default-branch repoint)
and one verification step (confirm an actual scheduled run landed a
`forward-capture-bot`-authored commit) before this can be called done.
Until then, classify hourly capture as **PARTIAL**: the deterministic
script exists in two forms, the externalization code exists, but the
externalized *schedule* has not been proven to fire even once.

### 2b. Daily loop

**EXISTS:**
- `scripts/daily_loop.sh` (101 lines) — snapshot/ingest via `python3 -m
  src.cli daily`, ledger status read, then the same shared-lock
  commit-and-push discipline as forward capture (same
  `/tmp/linehound_git.lock`, same rebase-before-push, same `ESCALATE:`
  convention) — explicitly documented as the second writer that made the
  shared lock necessary in the first place (four stranded/mismerged
  commits in 30h before the fix, named by commit hash in the script's own
  header comment).
- Documented cadence: "daily 10:00 UTC" in `docs/RUNBOOK.md:8`.

**CLAIMED-BUT-ABSENT:**
- No GitHub Actions workflow runs `daily_loop.sh`. `.github/workflows/`
  holds exactly three files (`deploy-staging.yml`, `forward-capture.yml`,
  `tests.yml`); none references `daily_loop.sh`. The "daily 10:00 UTC"
  row in the runbook's "what runs on its own" table is describing an
  **intended** external trigger (a scheduled Routine calling into a
  session), not a committed scheduled job — there is no `cron:` anywhere
  in the repo for it. `docs/CAPTURE_EXTERNALIZATION.md`'s own "Known
  follow-up" section says exactly this: "Moving the daily loop to a
  10:00Z Actions job is the next step once the capture job has run for a
  day" — future work, not done. So "daily 10:00 UTC" in the runbook table
  reads as settled fact but is, today, only as durable as whatever
  session/Routine is configured outside this repo to fire it — the repo
  itself has no artifact proving it happens unattended.
- Same for the "4-hourly autonomous build loop (roadmap queue)" row in
  the same table (`docs/RUNBOOK.md:9`, "model session, works
  docs/ROADMAP.md") — there is no script, no workflow, nothing under
  `scripts/` or `.github/workflows/` implementing a build loop. `grep -rn
  "build loop\|build_loop\|BUILD LOOP"` across docs finds only narrative
  references (`docs/OVERNIGHT_RUN.md:475` "build loop live") describing a
  session's own activity, never a scheduled artifact. This is the
  clearest example in the whole subsystem of the gap between "what the
  runbook's table implies runs on its own" and "what is actually wired to
  run without a human/session initiating it."

**BOOST vs REPLACE:** the underlying script is fine (BOOST it); the
scheduling claim needs correcting in the runbook or actually built —
right now it's a table entry describing an aspiration, and an operator
reading `docs/RUNBOOK.md` at face value would believe more automation
exists than does.

### 2c. Monitor (hourly health check)

**EXISTS, well-hardened:**
- `scripts/monitor_remote.sh` (207 lines) — curls a deployed base's
  `/health`, classifies curl's exit code into a named failure class
  (`TLS_RESET`, `RECV_RESET`, `CONN_REFUSED`, `DNS`, `TIMEOUT`,
  `EMPTY_REPLY`, `HTTP_503`, `HTTP_5XX`, `HTTP_4XX`), keeps a state file
  under `/tmp/linehound_monitor/<url-key>.state` (overridable via
  `MONITOR_REMOTE_STATE_DIR`) implementing a real escalation ladder: 1st
  failure = recheck silently, 2nd+ = `ESCALATE: N consecutive failures,
  class=<CLASS>`, one `RECOVERED:` line on the first OK after any
  escalated run, and a class change mid-incident resets the count and
  re-escalates on the new class's 2nd occurrence. Hardened 2026-09-01
  after a real 5-hour staging outage (Fly billing suspension) that this
  exact classifier now names on sight.
- `docs/OPERATIONS_RUNBOOK.md` gives this monitor a full decision tree
  (§1's table) mapping each failure class to a first move, plus §2a-2c
  recovery playbooks (billing check, machine/process recovery, token-less
  GitHub Actions redeploy fallback), a backup-verification section (§4,
  paired with `scripts/backup_app_db.sh`), a Stripe-failure-visibility
  table (§5), and a deploy-failure-alerting section (§6) — this is easily
  the most complete, evidence-grounded runbook in the subsystem, written
  as a direct postmortem artifact rather than aspirational prose.

**PARTIAL / CLAIMED-BUT-ABSENT:**
- Nothing in this repo actually *calls* `monitor_remote.sh` on a
  schedule. No `.github/workflows/*.yml` references it, and there is no
  cron/trigger config file anywhere in `.claude/` or elsewhere in the
  tree. The doc's own words are explicit about this being a design, not
  a deployed schedule: "`scripts/monitor_remote.sh` (hardened 2026-09-01)
  now prints a failure class... Use that class to jump straight to a
  branch below" — but *who* runs it and *how often* is left as "the
  hourly monitor" in narrative (`docs/OPERATIONS_RUNBOOK.md:6`: "The
  hourly monitor caught it (or **would have**, under this file's hardened
  version of it)") — the parenthetical concedes the hardened version
  postdates the actual outage and its own recurring invocation is not
  demonstrated in-repo.
- §2d of the same doc is explicitly self-labeled "PROPOSED — not applied"
  — a Fly `restart_limit` config block the operations doc recommends but
  that no file in `deploy/fly.staging.toml` implements yet. Confirmed: this
  is documentation of a suggestion, correctly labeled as such, not a
  claimed-but-absent case (it doesn't claim to be live).
- Fly credentials are explicitly and deliberately never given to any
  agent session (`docs/OPERATIONS_RUNBOOK.md:12-16`, "No agent session in
  this program holds Fly credentials by design") — meaning even if a
  scheduled trigger ran `monitor_remote.sh` and it escalated, the
  recovery half of the runbook (§2a/§2b, `fly` commands) is **structurally
  incapable of being executed by any automated system in this repo** —
  it is written for "Launch Ops / Brey" by name. The one exception,
  correctly separated out, is §2c's token-less GitHub Actions redeploy
  fallback, which an agent session *with GitHub MCP tools* can fire
  (`mcp__github__actions_run_trigger`) without ever touching a Fly
  credential — that path is real and does not require the human.

**BOOST vs REPLACE:** BOOST the script and runbook as-is; the missing
piece is wiring an actual recurring trigger (a Routine, or a GitHub
Actions `schedule:` job hitting the same default-branch constraint
`forward-capture.yml` has) to invoke `monitor_remote.sh` and forward its
`ESCALATE:`/`RECOVERED:` lines somewhere a human sees them — today that
loop is closed only when an interactive session happens to run it or a
human happens to check the health endpoint by hand.

---

## 3. Adversarial review as a standing gate

**EXISTS, but as one dated instance, not as an enforced pipeline step:**
- `docs/ORCHESTRATION_DAY_2026-09-02.md`'s "RESEARCH RESULTS" section
  documents one concrete adversarial-review cycle: the V3
  `transaction_first_seen` first read "FAILED adversarial review on nine
  required findings," was corrected same-day as ADDENDUM 2, and passed a
  second review — catching "a manufactured positive within four hours of
  its creation" (listed under "MORE IMPORTANT THAN WE THOUGHT"). This is
  real, evidenced, and exactly the mechanism the vision wants
  ("Opus on... adversarial review").
- `.claude/agents/opus-validator.md` is the corresponding role file:
  "Your job is to try to FAIL it," re-run every acceptance check, read the
  diff adversarially for named failure classes (leakage, fabricated
  values, off-by-one cutoffs, sealed-data access, credit-spend paths,
  bet-placement capability, terminology drift like calling price
  improvement "EV"), run the full parallel suite, PASS/FAIL report with
  blocking vs non-blocking concerns separated. `opus-redteam.md` is the
  sibling role specifically for hunting real bugs with reproductions.

**MASTER-PLAN-LEVEL CLAIM, NOT YET CODE:**
- `docs/ORCHESTRATION_DAY_2026-09-02.md`'s "MASTER PLAN CHANGES" section
  states a new rule was *added*: "Phase 1 gate added: a research read is
  valid only if pinned (commit + hashes of every store it reads,
  git-ignored ones included) and only after an adversarial review
  passes." This is a policy decision recorded in a narrative doc, not a
  gate enforced by any code path — nothing in `src/research/` or
  `src/evolab/` checks "has this been through opus-validator" before
  accepting a result. The gate today is: a human/orchestrator remembers
  to ask for a validator pass. `docs/ORCHESTRATION_DAY_2026-09-02.md`'s
  own "NOT THINKING BIG ENOUGH" section names this exact gap ("The review
  loop should be a standing gate on every addendum, not an orchestrator
  decision") — i.e., the project's own end-of-day synthesis already
  classifies this as CLAIMED-BUT-NOT-YET-STRUCTURAL, matching this map's
  independent read.

**BOOST vs REPLACE:** BOOST — the role file and the one real precedent
are the right shape; what's missing is a mechanical trip-wire (e.g., a
research-result file format that literally cannot be marked "read" until
a `validator_verdict` field is populated) rather than relying on the
orchestrating session's memory.

---

## 4. Worktree store-completeness rule & pinned reads

**EXISTS as a documented rule with real, cited failures behind it, but NOT
as enforced tooling:**
- `docs/ORCHESTRATION_DAY_2026-09-02.md` "LEARNED" section, verbatim
  reproductions of real incidents:
  - "Worker environments silently miss git-ignored stores. Two lanes
    produced wrong counts for exactly this reason (42 vs 56 measurable,
    twice, via two different stores). Rule: research lanes copy the
    stores they read read-only into the worktree and hash them in the
    addendum."
  - "Pinned reads are not optional: the same CLI command returned
    166/165 and 168/167 to two readers because capture appended between
    them."
  - "`git pull --rebase` over unpushed merge commits flattens them; the
    capture script's own rebase did this to one merge (L20) during a
    restart. Content survived, the merge commit did not. Push merges at
    once."
- L16 (the corrected V3 read, ADDENDUM 2) is cited as the concrete
  instance that actually did this right: "pinned read (commit + nine
  store hashes incl. both git-ignored stores)" (`ORCHESTRATION_DAY_
  2026-09-02.md:89-90`).
- `tests/test_forward_evidence_tracked.py` exists and is invoked by name
  in `docs/RUNBOOK.md:132` as the check for whether a forward store's
  path is git-tracked — the closest thing to enforced tooling for the
  "don't silently lose a store" half of this problem.

**MISSING (named as a gap by the project's own docs, confirmed absent in
code):**
- "NEXT (queued, not started)" in the same doc lists "Store-completeness
  helper for research worktrees; addendum template with the pin section"
  — i.e., the rule is written down as prose convention that a Sonnet/Opus
  worker must remember to follow by hand each time, not a script that
  copies+hashes the relevant stores automatically before a research lane
  starts. No `scripts/*store*complet*` or equivalent helper exists
  anywhere in `scripts/`. No addendum *template* file exists under
  `docs/` (each addendum, e.g. the V3 corrections, is hand-written prose
  following the convention by discipline, not by a filled-in template
  enforcing the pin section).
- There is no code that hashes "every store a research lane reads,
  git-ignored ones included" automatically — the L16 precedent did this
  by hand, once, as a corrective response to having gotten it wrong
  twice already.

**BOOST vs REPLACE:** the rule is right and the incidents proving its
necessity are well-documented; this needs a genuinely new small tool
(BOOST as an addition, nothing here to replace) — a `scripts/pin_read.sh`
or equivalent that snapshots+hashes the named stores into a worktree and
emits the addendum's pin section automatically, so the next lane can't
skip it by forgetting.

---

## 5. Budget / credit governors

**EXISTS in code, with real enforced floors:**
- `src/pipeline/dense.py:62` — `CREDIT_FLOOR = 5000` (matches
  `docs/COLLECTION_POLICY.md`'s "floor 5,000, absolute"), checked before
  capture and again before the close pass (`dense.py:305`, `dense.py:378`
  both return `{"skipped": "credit floor", ...}` rather than spending
  through it). `docs/RUNBOOK.md`'s failure playbook treats "skipped:
  credit floor" as a hard stop by design: "spending stopped by design.
  Decide whether to raise budget; nothing resumes spend without you."
- `docs/COLLECTION_POLICY.md` documents a layered spend policy on top of
  the hard floor: a ~132 credits/day approved envelope, enforced "in code
  order: if a day would exceed it, added markets are skipped first, then
  the grid thins" — a three-layer BASELINE/EVENT/CLOSE/SOFTER-MARKETS
  structure with the soft layer (F5 h2h piggybacked on dense moments)
  explicitly bounded and estimated (+15-40 credits/day).
- `python3 -m src.cli credits` and the credit-balance log
  (`src/pipeline/creditlog.py`, wired into `capture_extras.sh`) give a
  running balance an operator or a script can check
  (`docs/RUNBOOK.md:18`, "credits above 5,000 floor? (~132/day burn)").
- Prop *listing* (feasibility, 0 rows of price data) vs prop *pricing*
  (real spend) are deliberately separated with a second, independent
  switch: `PROP_LISTING_AUDIT="on"` in `forward_capture.sh`/
  `capture_slot.sh` (a bounded, time-limited, 400-credit-capped probe per
  `docs/PROBE_PROP_LISTING.md`) and `PROP_PRICES` (off by default, must be
  explicitly set to `"1"`) in `capture_extras.sh` for the priced layer —
  two separate governors for two different risk levels, each a one-line
  env flip with no code change required to kill it.

**PARTIAL:**
- The 132/day envelope is enforced by narrative discipline in the pipeline
  ("Actual spend has run far below the envelope... this policy uses
  deliberately") rather than by a single hard-coded daily cap constant the
  way `CREDIT_FLOOR` is — there is a floor, but the *ceiling* language in
  `COLLECTION_POLICY.md` reads as intent for how markets get thinned, not
  as a single asserted number anywhere that a test pins. This map did not
  find a `DAILY_CREDIT_ENVELOPE = 132` (or similar) constant to cite
  alongside `CREDIT_FLOOR`; the днvelope currently is a documented policy
  that the actual spend has stayed under by a wide margin (headroom
  discussed explicitly), not something enforced by a hard stop the way the
  floor is.
- No governor exists yet for *worker/session* spend (API cost of the
  Opus/Sonnet/Fable workers themselves, as distinct from odds-provider
  credits) — the vision's "budget and credit governors" plausibly means
  both; only the data-provider-credit half is implemented.

**BOOST vs REPLACE:** BOOST — `CREDIT_FLOOR` and the switch-based
governors are a good, cheap, verifiable pattern; a literal
`DAILY_ENVELOPE` constant checked the same way `CREDIT_FLOOR` is would
close the partial gap and make "132/day" a testable invariant instead of
an observed-so-far pattern.

---

## 6. Alpha registry consumption rules

**EXISTS, both design and implementation:**
- `docs/ALPHA_REGISTRY_DESIGN.md` (112 lines) — the design record:
  canonical unit = registered hypothesis (V1 21 + V2 5 + V4 6 + V5 3 =
  35), a sweep (e.g. Evolab Phase 2B's 8,811 genomes) counted as ONE
  registry entry carrying its own within-sweep correction rather than
  8,811 separate charges (rationale: double-counting vs. hiding search,
  explicitly reasoned through), append-only JSONL row shape with
  `hypothesis`/`sweep`/`audit` registration rows and a separate `verdict`
  row appended on read, v0 semantic-hash-based duplicate detection
  (sha256 of sorted (feature, operator, market, direction) atoms with
  thresholds bucketed to the family's grid).
- `src/research/alpha_registry.py` (471 lines) — the implementation.
  `docs/ORCHESTRATION_DAY_2026-09-02.md` reports it seeded with 40
  hypotheses + 1 sweep + 1 audit + 38 verdicts + 1 withdrawal
  (`data/research/alpha_registry.jsonl`), with a migration report.
- **Decision 4 (consumption rules), as designed:** (a) any new family's
  pre-registration doc must cite `alpha_registry.total_searched(market,
  data_window)` — "searched before this family: N units, K sweeps, on
  these windows"; (b) the learnability audit reports per-market
  searched-so-far alongside structure metrics; (c) "Evolab v2's nightly
  cycle may not register a genome whose v0 hash is already in the
  registry with a verdict on the same data window."

**NOT VERIFIED AS ENFORCED (scope boundary — this map did not audit
`src/evolab/` or the research pipeline's call sites; noting the boundary
rather than asserting either way):** whether `total_searched()` is
actually *called* by every family's pre-registration doc-generation path,
and whether Evolab's nightly-cycle code actually checks the registry
before registering a genome (Decision 4's clause c), is a claim about
`src/evolab/` and `src/research/battery.py` call sites that belongs to
the compute-scale/research subsystem's map, not this one — flagged here
so it isn't silently assumed true by omission. The registry file and its
design doc are real; whether every consumer actually calls it is outside
this subsystem's read.

**BOOST vs REPLACE:** BOOST — this is one of the more mature, carefully
reasoned pieces of the whole program (explicit rationale for the
double-counting decision, a real acceptance checklist for the
implementation packet). Worth a targeted follow-up read of `src/evolab/`
call sites to confirm Decision 4 is wired, not just declared.

---

## 7. What exists as scripts vs. what exists only as habit

Summary table, since this is the central question this subsystem was
asked to answer:

| Loop | Script exists? | Scheduled trigger exists in-repo? | Verified actually firing unattended? |
|---|---|---|---|
| Hourly forward capture (legacy) | Yes — `forward_capture.sh` | No (relies on an external session/Routine) | No artifact in this repo proves it |
| Hourly forward capture (externalized) | Yes — `capture_slot.sh` | Yes — `forward-capture.yml`, `cron: */15 * * * *` | **No** — blocked on default-branch repoint; zero `forward-capture-bot` commits in history |
| Daily loop (10:00 UTC) | Yes — `daily_loop.sh` | **No** | No |
| 4-hourly build loop (roadmap) | **No script at all** | **No** | No — pure narrative in the runbook table |
| Health monitor | Yes — `monitor_remote.sh` | **No** | No — invoked ad hoc / by an interactive session |
| Deploy on push | Yes (`flyctl deploy` in the workflow) | Yes — `deploy-staging.yml`, `on: push` + `workflow_dispatch` | **Yes** — 80+ green runs cited (`COMMAND_CENTER.md:83`), and this workflow's trigger (`on: push`) is not subject to the default-branch `schedule:` constraint, so it is the one loop in this table actually proven to run unattended |
| Tests on push/PR | Yes | Yes — `tests.yml`, `on: push`/`pull_request` | Yes — same reasoning, push-triggered not schedule-triggered |
| Backup | Yes — `backup_app_db.sh`, hardened with integrity check | **No** — `docs/OPERATIONS_RUNBOOK.md §4` states plainly: "Nothing currently fires it on Fly — it still needs wiring... once a scheduler has Fly access to the staging app" | No |

The pattern: **push-triggered** GitHub Actions work and are proven
(deploy, tests); **schedule-triggered** GitHub Actions (`forward-capture.yml`)
is blocked by the orphan-default-branch problem and unproven; anything
that was never given a workflow at all (`daily_loop.sh`, the build loop,
`monitor_remote.sh`, `backup_app_db.sh`) exists purely as a script an
interactive session or a human is expected to remember to run.

---

## 8. What runs where — the actual constraint map

- **GitHub Actions**: the only place with genuinely independent-of-
  container execution and a real credential story (repo secrets,
  auto-scoped `GITHUB_TOKEN`). Confirmed working for push-triggered jobs.
  Blocked for schedule-triggered jobs by the default-branch orphan issue.
  Zero cost (public repo, unmetered Actions minutes) — this is a real,
  checked fact (`docs/CAPTURE_EXTERNALIZATION.md` fact 6, "confirmed via
  the GitHub API by the orchestrator"), not an assumption.
- **Interactive/session container**: everything else today, including the
  daily loop, the build loop, and (until proven otherwise) the actual
  hourly capture cadence. Explicitly fragile: "The container restarted
  twice in twenty minutes when the full suite (4 workers), a dense
  capture and two Playwright lanes overlapped, and each restart dropped
  scheduled-trigger messages and untracked files" (`ORCHESTRATION_DAY_
  2026-09-02.md`, LEARNED) — this is the exact failure class L25 was
  built to remove from capture, and it still applies unmitigated to the
  daily loop, the build loop, and the health monitor.
- **Fly**: hosts the customer-facing web app only (`linehound-staging`).
  Deliberately holds **no** odds-provider credential and **no** agent
  session ever holds its deploy credentials — recovery there is
  human-only by design (`docs/OPERATIONS_RUNBOOK.md`'s scope note). The
  one Fly-adjacent automation that exists and is proven is the
  push-triggered redeploy; a Fly-hosted capture process (Option B in
  `CAPTURE_EXTERNALIZATION.md`) was considered and explicitly rejected
  for now (new spend, new credential, unsolved distributed-lock problem).

---

## Data that becomes unrecoverable if not captured now

Specific to this subsystem (orchestration/ops), as distinct from the
market data itself:

1. **The actual first-fire timestamp and behavior of `forward-capture.yml`
   once the default branch is repointed.** Once it does fire, whether it
   collides with a still-active in-session Routine (two writers, no
   cross-host lock) is a one-time-observable race condition; if it
   corrupts or strands a commit the way the pre-lock-era captures did,
   that is exactly the kind of incident `docs/ORCHESTRATION_DAY_
   2026-09-02.md`'s LEARNED section wants captured, not silently
   resolved by a lucky rebase.
2. **Container-restart incident data.** The four-restarts-in-under-an-hour
   pattern on 2026-09-02 (LEARNED section) is currently recorded only in
   prose; if this environment's restart behavior is itself
   time-varying (load-related, platform-related), losing the ability to
   correlate future restarts against what was running at the time (heavy
   suite + dense capture + Playwright, all at once) means losing the
   ability to ever confirm or rule out "load" as the cause — the doc
   itself says "Not load; needs the platform or a different environment"
   but that conclusion rests on this one day's data.
3. **The pinned-read precedent itself (L16's nine store hashes + commit).**
   If that specific addendum is ever edited or the hashes not preserved
   verbatim, the one existing worked example of "how to do a pinned read
   correctly" is gone, and the next research lane has only the prose rule
   to work from, not a template to copy.
4. **`docs/OVERNIGHT_RUN.md`'s incident log** (referenced repeatedly as
   the durable home for "missed capture windows... never backfilled") is
   the only place a missed window's exact timestamp and reason survive;
   `docs/RUNBOOK.md:126-127` states this is deliberate ("gone forever;
   logged in docs/OVERNIGHT_RUN.md. Never backfilled") — meaning if that
   file itself were ever lost or truncated, so is the entire missed-window
   history, with no secondary source.

---

## Key numbers (cited, with file:line)

- `CREDIT_FLOOR = 5000` — `src/pipeline/dense.py:62`.
- Approved daily envelope: ~132 credits/day — `docs/COLLECTION_POLICY.md:4`.
- Credit balance at last cited check: ~52,990–53,083 (two close but
  distinct citations: `docs/COMMAND_CENTER.md:5` and
  `docs/COLLECTION_POLICY.md:3`); 99,680 remaining reported later the same
  day (`ORCHESTRATION_DAY_2026-09-02.md`, FALSIFIED section, "Credits are
  scarce" flagged as false at 21:00Z) — the swing across one day is itself
  worth noting for anyone treating any single balance snapshot as current.
- Test suite size/timing: 3,186 tests at 20:10Z pre-Wave-1, 2,981 fast-tier
  at 21:47Z post-restarts, full parallel run "~9 minutes... (27s in a
  fresh worktree)," fast tier "6s" (`ORCHESTRATION_DAY_2026-09-02.md:12-19,37`).
- Forward-capture externalization: 15-minute cadence, `capture_slot.sh`
  104 lines, `forward-capture.yml` created 2026-09-02 (L25,
  commits `d01348d`/`04d1e4f`/`43972e9`).
- Zero `forward-capture-bot`-authored commits found in `git log --all`
  at read time — the concrete evidence behind "unproven, not yet firing."
- Six `.claude/agents/*.md` files, all `model: opus`, zero `sonnet`/
  `fable` role files.
- Alpha registry: 40 hypotheses + 1 sweep + 1 audit + 38 verdicts + 1
  withdrawal seeded (`ORCHESTRATION_DAY_2026-09-02.md:81-82`); design doc
  is 112 lines, implementation is 471 lines (`src/research/alpha_registry.py`).
- Default branch: `claude/cowork-session-migration-tn3sx2` (orphan, no
  shared history with the working line) — confirmed live via
  `git remote show origin` at read time, matching the doc's own claim.

---

## One-line classification summary (for the structured output)

See the tool call's structured fields for the compressed version of every
item above; this file is the evidence backing each line.
