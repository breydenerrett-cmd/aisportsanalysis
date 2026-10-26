# Overnight queue: Mon Oct 26, 2026 (autonomous)

Rules: one or two cheap workers at a time (Haiku by default, Sonnet only where accuracy needs it, no Opus unless a money-path review is essential). Before every push, run every test that references a changed file, under both pytest and the no-FastAPI harness. Push, wait for CI, deploy on green, then check the live site. When something is blocked, park it below with the reason and move to the next item.

| # | Item | Status |
|---|---|---|
| 1 | Apprentice Hound + DraftKings screenshot import (owner, evidence grades A–D, append-only lessons, parlay = all legs) | in progress |
| 2 | QA walk of the live site on phone and desktop, every page and main flow, logging broken or ugly items | queued |
| 3 | Fix batch from #2 | queued |
| 4 | NHL odds captured in time for 3-hours-out rule checks (HOCKEYCHIEF "no fresh board yet"), within the data budget | queued |
| 5 | Jarvis pre-game briefing, built on LINEHOUND data only, with experimental labels | queued |
| 6 | Feedback loop: owner votes feed training; Bad call gets what-was-wrong chips; daily digest; backlog entry; a reply when fixed | queued |
| 7 | Learner Hound (merged with Apprentice phase 2) and the AI-hound mascot | queued |
| 8 | Live page redesign (low priority) | queued |

## Parked (needs Brey)
- Desk hounds: block both-lose pairs? (recommended yes)
- Privacy/terms blanks: name, contact email, postal address, governing-law state (branch worker/legal-pages)
- Apple Developer ($99) / Google Play ($25) enrollment, then TestFlight via docs/mobile/MAC_SETUP.md
- Push alert keys: `python scripts\vapid_keys.py --app linehound-prod`
- Pause the scheduled "LineHound daily autonomous run" (it collides with pushes)
- EuroLeague / other hockey / cricket fast grading: no free ESPN source. The 2-hour path and 72h void stay until a source is found.

## Record
- DK639285386193890132 (Dobbins O49.5 + Irving O64.5, +253, $100.18): LOST. Irving 24-106, Dobbins 6-23 (ESPN final box scores).
