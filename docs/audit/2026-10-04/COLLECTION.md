# Collection: one fetch, reused everywhere (2026-10-04)

Branch `worktree-agent-abd23ebcbb0e6ccd4`. Scope: the MLB request-time stores
under `data/historical/`, refreshed from MLB's free Stats API by
`src/pipeline/display_refresh.py`.

## 1. TL;DR

Every consumer started from the committed copy (ends 2026-09-23) and re-fetched
the whole gap. One cold refresh is **632 requests, about 3.5 minutes**. About
**57 image builds a day** each did that, so the same upstream data was asked for
about **36,000 times a day** (upper bound: it assumes every build ran the whole
gap) when the new information in a day is a few dozen requests.

Fixed by (a) counting and reusing requests in one layer, (b) not re-asking for
what a store already holds, and (c) giving the daily loop a safe way to persist
the refreshed stores (a union with git, never a replace). After the daily loop
has run once, a build's refresh is **about 5 requests** (measured) to about 25
(a postseason day behind, measured). Modeled: **about 600 requests a day
instead of about 36,000.** That is a model from measured unit costs. It becomes
a measurement after the first daily loop commits the stores and a day of builds
has run; nothing here has been deployed.

Nothing here cuts a bill. All of this traffic was free and keyless. What still
costs money is in section 7.

## 2. Measured, before (the number written down first)

Method: `src/pipeline/refresh_fetch.py`'s `FetchLayer` installed around the
**unmodified** `display_refresh.refresh()` in passive mode (no reuse, no retry),
on a copy of `data/historical/` (the committed copy), `--max-seconds 600`, the
real API, one request at a time, 2026-10-04. `wire_attempts`
counts real `urlopen` calls and agrees with the call count (633 against 632;
the one extra is the provider's own retry of a timeout).

| One refresh, committed copy as it stands | Requests | Seconds |
|---|---|---|
| **Before, cold (stores end 2026-09-23, pitcher logs 09-07)** | **632** | **211** |
| of which schedule | 44 | |
| boxscore (bullpen) | 288 | 116 (bullpen step) |
| pitcher game log | 271 | 79 (pitchers step) |
| standings | 19 | 6 |
| splits 6, handedness 1, Savant 2, transactions 1 | 10 | |
| Before, steady (the store the first run just produced) | 19 | 10 |
| of which schedule 8, boxscore 4, splits 6, transactions 1 | | |

12 URLs were asked twice in the cold run, and 2 in the steady one (the probe,
the results step, the pitcher step and the splits step all ask for the same
schedule days).

### Who asked, as configured today

| Consumer | Frequency | Cost each |
|---|---|---|
| `deploy-prod` image build (`RUN python -m src.pipeline.display_refresh`) | 17 successful runs on 2026-10-03 (29 dispatched; 12 cancelled), 15 by 14:00Z on 10-04 | a cold refresh (632) from the checkout's copy |
| `deploy-staging` image build (push to the branch touches `data/processed/**`) | 40 successful runs 10-03; 18 on 10-02; 24 on 10-01 | same |
| container guard (`start_background_guard`), production and staging | hourly check, refreshes only when a core store is stale | 0 after a fresh build |
| daily loop's own catch-up | once a day | results, standings, splits (about 29 probables), arsenals: about 35 |
| a local run | whenever | 632 |

57 builds on 10-03 x 632 = **about 36,000 requests**, 3.5 minutes of build time
each. Run list read with `gh run list` (counts above are from that output).

## 3. The problem chosen, and why

Candidate problems: team totals not captured (a paid feed; see section 6), the
MLB stores refetched by every consumer (free, but it makes every build 3.5
minutes longer, hammers a provider whose terms say individual non-commercial
use, and was the stale-site cause), UFC and NFL layers (already incremental and
cached by URL, 4 requests for an NFL update). The MLB refetch is the largest by
three orders of magnitude and the only one that blocks real analysis: every
brief built on a checkout started "11 days stale" until a 2.5-minute manual
refresh. Team totals are a deliberate pause, not a defect.

## 4. What changed

| File | Change |
|---|---|
| `src/pipeline/refresh_fetch.py` (new) | One layer at the three network seams (`mlb._get_json`, `mlb_news._get_json`, `statcast.fetch_arsenal`): counts calls and real wire attempts per endpoint class; answers an identical URL from memory within a run; keeps answers that can never change (a schedule day whose games are all final or cancelled, the boxscore of a game shown final) on disk under `<data>/raw/mlb_statsapi_cache/` keyed by canonical URL (same `canonical_url` as `PoliteFetcher`), 7-day trust; retries 429/5xx at most twice (1 s, 2 s, `Retry-After` up to 30 s); **a 401/403 halts the whole run at once, no retry, every later call fails with no request**; 3 calls still 429, or 6 hard failures in a row, also halt; classifies every call |
| `src/pipeline/display_refresh.py` | `refresh()` runs inside that layer; per step `fetch` counts and an `observation` (new, corrected, unchanged, missing_source, failed, verdict); yesterday's bullpen re-fetched only when the schedule shows a final game the log lacks (was: always, 4 to 15 boxscores); a cached split under 12 h old not re-asked for; an upcoming probable checked under 30 h ago with no newer start not re-asked for; a halted run skips every later step; `row_diff` |
| `src/pipeline/store_persist.py` (new) | `union`/`persist`: merge the disk copy with `HEAD`'s copy record by record (see 5) and list the stores that then differ from `HEAD` |
| `scripts/daily_loop.sh` | two guarded additions: merge-with-git then incremental refresh (before the git lock, after every pricing and settling step), and under the lock, union with `HEAD` and stage the differing stores **by name** behind `guard_staged_no_shrink` |
| tests | `tests/test_refresh_fetch.py` (21), `tests/test_refresh_incremental.py` (20), `tests/test_store_persist.py` (19), `tests/test_daily_loop_persist.py` (8, runs the real shell block in a throwaway git repository) |

Two existing tests pinned a consequence that the change made untrue and were
edited, not deleted: `test_display_refresh_keys` (a blip on yesterday's
schedule used to drop the rows and have the per-key promotion put them back;
now the rows are never dropped, so nothing is restored) and
`test_display_refresh` (the data root now also holds `raw/`, the fetch cache).

Files I did not touch: `api/datasvc.py`, `src/datasvc/`, `src/providers/`,
`deploy/Dockerfile`, `.github/`. `src/providers/mlb.py` already retries a
timeout or reset once and raises on every HTTP status; the layer sits above it
rather than editing it, which is why the transport failure is not retried twice.

## 5. The union, and why it is safe

`store_persist` uses the refresh's own per-store keys and record identities
(`display_refresh.KEYED_STORES`), so there is one definition of a record:

* a record only git holds **survives**;
* a record both hold takes the primary side's version: `prefer=disk` just before
  committing (the disk copy was refreshed from the API minutes ago, so a provider
  correction wins), `prefer=head` when seeding a runner (git is the durable copy;
  an old Actions-cache restore can never overwrite what git knows);
* the two Savant leaderboards are snapshots, the later `as_of` wins whole;
* a merge that would still lose a record the other side holds is **refused**
  (checked by running the repair the other way), an unparseable file is refused,
  and the disk copy is replaced atomically and only when the merge differs.

Proof on real data (not in the committed tree): the 2026-10-04 refreshed stores
with the 131 postseason games of 2023-25 removed from `mlb_results.csv`, to look
like an Actions-cache copy, were unioned with this branch's `HEAD`: all 9,747
committed games present, 131 restored, 69 added; every one of the 59,800
committed bullpen rows present. Tests pin: a row only git holds survives; a
corrected row is updated and not duplicated; an old cache cannot beat git; the
union is idempotent; a lossy merge is refused; and the real `daily_loop.sh`
block, run under bash in a throwaway repository, stages a blob that holds the
git-only game, the new game, the corrected score.

I did **not** commit any refreshed `data/historical` file. The first daily loop
after this merges does it, by the design above. (A one-off
`python -m src.pipeline.display_refresh` then `python -m src.pipeline.store_persist persist`
on a checkout, and staging the printed paths, would make the committed copy
current now.)

## 6. Capture finding: team totals and props

* **Team totals are not scheduled, on purpose.** `scripts/capture_slot.sh` passes
  `DERIVATIVES="${DERIVATIVES_CAPTURE:-0}"` to `capture_extras.sh`; no workflow
  sets `DERIVATIVES_CAPTURE`, so `src/pipeline/derivative_markets.py` prints
  "off" and buys nothing. The comment says it was paused for the 2026-09-21
  credit squeeze (`docs/drafts/CREDIT_TRIM_PLAN_2026-09-21.md`), and the data
  agrees: the last row in `derivative_markets.jsonl` was observed
  2026-09-21T22:19Z, a Tigers game. It is not a postseason gap: the same switch
  would hold in September. The module has no per-family switch (`FAMILIES` is
  fixed), so resuming it resumes team totals, alternates and the F5 trio together,
  about 96 credits a day by the script's own estimate; team totals alone cost 1
  credit per event per slot (`config/capture_families.json`; its one probe was
  flagged degenerate, 3 books). The exact one-line patch is
  `docs/decisions/derivatives-capture.patch` (`git apply --check` clean). It is a
  workflow edit and an owner credit decision; nothing was bought or changed.
* **Props are scheduled for postseason games.** `batter_props.jsonl` holds
  baseline captures at 04:07Z and 04:18Z on 10-04 for the 10-04 and 10-05 games
  (the baseline window was widened to T-24h on 2026-09-14) and gate captures at
  T-2h for each of the 10-03 games; `prop_prices.jsonl` holds pitcher-strikeout
  slots (T-3h, T-90m, T-30m) through 10-03 21:37Z for the 10-04 00:30Z game. So
  "only 4 prop contracts for the next game" is what existed when that brief was
  built: the next game's gate capture opens 2 hours before first pitch and its
  strikeout slots T-3h, not earlier. I did not trace which packet read which
  store.

## 7. What still costs money, and the savings that are not savings yet

* **Upstream odds** (The Odds API): unchanged, and nothing here replaces it.
* **BALLDONTLIE ALL-ACCESS**: unchanged. Not examined beyond the matrix row.
* **Hosting** (Fly): unchanged. Shorter builds are a side effect; no plan changed.
* **Maintenance**: this adds two guarded steps and a union to maintain.
* The 36,000-to-600 request figure is free traffic, not money. It reduces build
  minutes, risk of being rate-limited, and exposure on the MLB terms question
  below. **Savings stay hypothetical until a plan is actually downgraded.**
* **A terms question the owner should see.** MLB's published terms (quoted in
  every Stats API response's `copyright` field, text at
  `gdx.mlb.com/components/copyright.txt`) permit "individual, non-commercial,
  non-bulk use" only and prohibit other use without MLB Advanced Media's written
  authorization. LineHound is a paid product that fetches in bulk. Reducing
  requests lowers the volume; it does not make the use licensed. Not resolved
  here. See the matrix in `docs/DATA_SERVICE_PLAN.md`.

## 8. Measured, after

Same method (the report's own `fetch` block; the same day, the same machine).

| One refresh | Requests made | Reused | Seconds |
|---|---|---|---|
| Cold, committed copy ends 2026-09-23 | **618** (632 before) | 0 | 194 |
| Same store, current, fresh disk cache (what a build costs once the stores are persisted) | **5** (19 before) | 4 | 12 |
| Same, immediately re-run on the same disk | 4 | 5 | 6 |
| One postseason day behind (10-03 rows removed, markers a day old; 4 games) | **25** | 6 | 14 |

Memory, for the 1 GB machine: a cold refresh peaked at **167 MB working set**
(154 MB committed) on Windows with the layer installed. The layer keeps only
schedule and standings answers in memory (a boxscore or a game log is asked for
once, so holding them would cost tens of MB for nothing). I did not re-measure
the old code on today's larger stores; the 134 MB in `STALE_DATA.md` section 4
was taken on 10-03 on a different copy, so the two are not a like-for-like
comparison. The guard's own 700 MB address-space cap is unchanged.

The cold case barely moves (14 fewer): it is real catch-up, and it is the one
that only has to happen once, in the daily loop, instead of in every consumer.
The 5 is 4 schedule days (today, yesterday, tomorrow, the day after) and 1
transactions call. A 15-game regular-season day behind is modeled, not
measured: about 15 boxscores, 30 game logs, 30 splits, a handful of schedules.

### Per day

| | Before (measured per refresh x configured consumers) | After (modeled from the measured unit costs) |
|---|---|---|
| Daily loop | about 35 (own steps) | 618 once, then about 25 to 100 a day, and it commits the result |
| Image builds, 57 a day | 57 x 632 = about 36,000 | about 14 builds in the six hours before the loop (04Z to 10Z) at about 25 + 43 builds at 5 = about 570 |
| Container guard | 0 after a build | 0 |
| **Total** | **about 36,000** | **about 600** |

The six-hour term is the largest left. It exists because the loop runs once a
day at 10:00Z and the Eastern date rolls at 04:00Z; persisting from a capture
slot too would close it, and I did not add that to the capture critical path.

## 9. Reliability, each with a test

| Requirement | Test |
|---|---|
| Bounded retries (429/5xx at most 2, capped backoff, `Retry-After` capped at 30 s) | `tests.test_refresh_fetch.RetriesAreBounded` |
| 401/403 stops at once, no storm, later calls make no request, news and Savant seams too | `AnAuthenticationDenialStopsAtOnce`; through the refresh: `tests.test_refresh_incremental.AnAuthenticationDenialStopsTheWholeRefresh` (one request on the probe, then every byte unchanged; mid-run, later steps skipped) |
| A failed or partial fetch keeps the good data | `TheReportSaysWhatItFound.test_a_failed_fetch_is_failed_and_the_good_data_is_kept` |
| New, corrected, unchanged, missing source and failed are distinguishable in the report | `TheReportSaysWhatItFound`, `EveryCallIsOneOfTheKindsAReaderMustNotConfuse` |
| A restart, or an old cache restore, does not discard the store | `ARestartDoesNotDiscardTheStore` (leftover work directory ignored and cleared; a disk cache from a previous process answers final games); `tests.test_store_persist` (`prefer=head`: an old cache cannot overwrite git, cache-only rows kept); `tests.test_daily_loop_persist` |
| Sealed window still never requested | `TheSealedWindowIsStillNeverAsked` plus the existing windows tests |

Restart behaviour in one line: every step still works on a copy in
`.refresh_work/` and promotes atomically, a killed run's leftovers are removed
at the next start and never read, and answers that cannot change are on disk, so
a rerun does not ask for them again.

## 10. Runs unattended, and how that was shown

The refresh runs through the daily loop with no session (`scripts/daily_loop.sh`),
as it already did through the image build and the container guard. Shown by
test, not by a live run on a runner: the extracted persist block, executed under
bash in a throwaway repository, stages the union and stages nothing when nothing
changed; a broken Python leaves the loop running and nothing staged; the text
tests pin the order (after every pricing and settling step, before the git lock;
persist under the lock before the add), `timeout` and a fallback on every line,
no errexit, and no directory-wide `git add`. Not shown: an actual Actions run.

## 11. Gaps

* Not run on a runner or in the Fly builder; the daily loop block is proven in a
  throwaway repository only.
* The "after" per-day figure is modeled; the cold, current and one-day-behind
  postseason cases are measured.
* The loop persists once a day; the 04Z to 10Z window keeps a small catch-up per
  build until a second persist point exists (a workflow or capture decision).
* `bullpen.build_log` still writes an empty-day marker when every boxscore of a
  date fails and resume never retries it (pre-existing; shared with the loop).
* The MLB terms question (section 7) is open.
* `tests.test_deploy_scripts...test_scripts_are_executable` fails on this Windows
  checkout for every script (file mode bits), before and after this work.

## 12. Reproduce

```
python -m src.pipeline.display_refresh --root <copy of data> --json report.json
python -c "import json;print(json.load(open('report.json'))['fetch'])"
python -m unittest tests.test_refresh_fetch tests.test_refresh_incremental \
  tests.test_store_persist tests.test_daily_loop_persist tests.test_display_refresh \
  tests.test_display_refresh_review tests.test_display_refresh_keys \
  tests.test_display_refresh_windows tests.test_display_refresh_guard
```
