# LINEHOUND to-do, paused until the usage reset (Sun Oct 25, 3 PM PT)

Owner directive (2026-10-22): usage is the top priority, so no building until the reset. Plans only.

## P0: correctness (do first on Sunday)
1. **Grade every sport fast.** The in-app loop misses UEFA soccer, EuroLeague, other hockey and cricket, so those tickets sat open 3–15 hours.
   - Add the ESPN league slugs, with accent/suffix name matching.
   - Show an honest "grading later" status for sports with no free source.
   - Fix the watchdog so it alerts on any ticket open 4+ hours past its start (it missed the cricket one).
   - Make the status page count tickets it can't see.
   - Branch fix/grade-all-sports exists but is empty.
2. **Ship Ask self-coaching + Apply/Veto/Tweak.** Checked and pushed at 22:15 UTC 10-22. Confirm GitHub's tests and the deploy, then check the live site.

3a. **Stop new sportsbooks from breaking CI.** Every new book key in the odds data fails test_labels and blocks deploys. This happened 3 times, most recently on 10-22: CI was red from 5 PM to 12:30 PM the next day, so no deploys went out and the grading fixes never shipped. Fix: an automatic fallback label built from the key, plus a watchdog note for new books, instead of a test failure.

3b. **Ungraded tickets block training for days.** Tarot Terrier's cricket ticket (NZ, 10-22) can't be graded, so training stays blocked until the 72h auto-void. Grading cricket (item 1) fixes most of it. Also show the "auto-voids at <time>" in the refusal message.
3c. **The training proposal still narrows a hound with 0 candidates today.** On Gematria Hound (2 settled bets) it proposed "Most bets a day 2→1". If today's candidate count is 0, offer loosening instead.

## P1: owner asks, planned and not started
3. **Feedback loop** (Good/Bad call):
   - Owner votes become evidence in training.
   - "Bad call" opens what-was-wrong chips.
   - A daily digest goes to Brey and Jacob.
   - Flagged issues go into docs/BACKLOG.md automatically.
   - The member is told when a fix ships.
4. **Desk hounds:** block both-lose pairs as a dated rule change (needs the owner's yes).
5. **"Who are you?" in Ask:** a real intro instead of a one-liner; no vote buttons on identity answers.
6. **Warm the "right now" cache at startup.** The first NFL call after a deploy takes about 15s.
7. **Live page redesign** (low priority, in docs/BACKLOG.md).

8. **The Learner Hound** (owner idea, 2026-10-23): a hound with no starting rules. It bets widely, then learns which patterns win and adapts, with AI and owner input on top. It becomes the brand mascot and an option in the quiz. Plan:
   - **Phase 1, explore:** paper-bet many small bets a day (cap 50–100) across markets, logging 20–30 features per bet: sport, price band, fav/dog, home/away, line move, books, rest, time.
   - **Phase 2, learn weekly:** fit a simple model (logistic regression or a small tree) on its own settled bets. Each new version is trained only on data before a cutoff, then tested forward on the next week before it may change how it bets. This is the guard against fitting to luck.
   - **Phase 3, adapt:** narrow toward segments that held up out of sample. Training, diagnosis, the Haiku read and the evolution animation already exist for showing this to the user.
   - **Owner input:** Ask/Retune can nudge it ("more hockey", "no favourites").
   - Honest framing: with vig, most patterns found this way are noise. The record shows it learning, never a promise.
   - Cost estimate: $15–25 to build on Sonnet. Running cost is mostly CPU, not Claude (the model is plain Python; Haiku only writes the weekly read).
   - Brand: "AI hound" mascot and logo is a design task, about $3–5 for SVG variants.

## Owner steps (no build cost)
- Apple Developer enrollment ($99): https://developer.apple.com/programs/enroll/ → Start Your Enrollment → Individual
- Google Play Console ($25): https://play.google.com/console/signup
- Push keys: run `python scripts\vapid_keys.py --app linehound-prod` (see docs/owner/ALERTS.md), then turn alerts on under Account → Alerts.
- Twilio + 10DLC for SMS (docs/owner/ALERTS.md).
- Privacy/terms blanks: name, contact email, postal address, state. These hold back the legal pages and account deletion (branch worker/legal-pages, already checked).
- Name your kennel ("Handler 27A3").
- Comp Jacob and yourself in admin.html → Add person → Give free access.
- Trading-bot notes: paste into that session yourself.

## Ready but parked (already checked, not merged)
- worker/legal-pages: privacy, terms, account deletion. Waiting on the owner blanks.
- worker/mobile-apps: /me/devices plus the Capacitor scaffold and plan. Merge when TestFlight work starts.

## Usage rules from Sunday on
- One builder at a time. A checker only for money, grading or auth changes.
- Sonnet by default, Opus only for hard bugs.
- No full-suite runs locally; Linux CI is the gate. The pre-push check runs only the tests that reference changed files.
- Batch small fixes into one worker instead of one each.
