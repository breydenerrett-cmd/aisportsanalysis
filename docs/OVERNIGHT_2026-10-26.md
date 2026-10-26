# Overnight queue: Mon Oct 26, 2026 (autonomous)

Rules: one or two cheap workers at a time (Haiku by default, Sonnet only where accuracy needs it, no Opus unless a money-path review is essential). Before every push, run every test that references a changed file, under both pytest and the no-FastAPI harness. Push, wait for CI, deploy on green, then check the live site. When something is blocked, park it below with the reason and move to the next item.

| # | Item | Status |
|---|---|---|
| 1 | Apprentice Hound + DraftKings screenshot import (owner, evidence grades A–D, append-only lessons, parlay = all legs) | pushed (02720c080); NFL props graded from ticket status only, no recommendation route yet |
| 2 | QA walk of the live site on phone and desktop, every page and main flow, logging broken or ugly items | done: 0 P0, 6 P1, 3 P2 |
| 3 | Fix batch from #2 | pushed (8e9df66c0); quiz reveal textarea overlap still open (needs an open-state measurement) |
| 4 | NHL odds captured in time for 3-hours-out rule checks (HOCKEYCHIEF "no fresh board yet"), within the data budget | pushed (574b56854): lock-time captures + 90-credit reserve, ~25 credits/day inside the same cap; details docs/NHL_LOCK_CAPTURE.md |
| 5 | Jarvis pre-game briefing, built on LINEHOUND data only, with experimental labels | deployed (ca95aa995): CLI + /admin/jarvis/brief; all numbers EXPERIMENTAL; no admin page section yet |
| 6 | Feedback loop: owner votes feed training; Bad call gets what-was-wrong chips; daily digest; backlog entry; a reply when fixed | pushed (34d240cee); digest email off until FEEDBACK_DIGEST_TO is set |
| 7 | Learner Hound (merged with Apprentice phase 2) and the AI-hound mascot | queued |
| 8 | Live page redesign (low priority) | queued |

## Parked (needs Brey)
- DISK FULL (C: 0 bytes free at 12:00 AM PT): about 120 GB is old test folders in %TEMP%, plus 46 GB in %TEMP%\claude. Deleting is blocked for me. Fix going forward is pushed (tests clean up after themselves). To clear the backlog, run in PowerShell:
  `Get-ChildItem $env:TEMP -Directory | ? { $_.Name -match '^tmp' -and $_.LastWriteTime -lt (Get-Date).AddDays(-1) } | Remove-Item -Recurse -Force`
- Two stuck local test processes (PIDs 34780, 35168, 26120): kill was denied for me; close them in Task Manager if the PC is slow
- Desk hounds: block both-lose pairs? (recommended yes)
- Privacy/terms blanks: name, contact email, postal address, governing-law state (branch worker/legal-pages)
- Apple Developer ($99) / Google Play ($25) enrollment, then TestFlight via docs/mobile/MAC_SETUP.md
- Push alert keys: `python scripts\vapid_keys.py --app linehound-prod`
- Pause the scheduled "LineHound daily autonomous run" (it collides with pushes)
- EuroLeague / other hockey / cricket fast grading: no free ESPN source. The 2-hour path and 72h void stay until a source is found.

## Record
- DK639285386193890132 (Dobbins O49.5 + Irving O64.5, +253, $100.18): LOST. Irving 24-106, Dobbins 6-23 (ESPN final box scores).
