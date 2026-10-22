# Why member tickets stayed PENDING for hours after the games ended (2026-10-22)

Owner report, ~06:00Z: Hornets @ Nets ML, Hawks @ Magic ML / spread / total and Bucks @ Wizards +4.5, all Oct 21 NBA
games, still PENDING 4-5 hours after they ended.

## How each kind of ticket settles (before this fix)

| Ticket | Ledger | Settled by | Score source | Where that source lives |
|---|---|---|---|---|
| Member and manual (`hound_user_bet`) | Fly volume, `hounds_user*.jsonl` | `user_settle.settle`, every 15 min in the API process (`user_runner`) | MLB `data/historical/mlb_results.csv`; NFL nflverse fetched at settle time; every other sport `data/processed/allsports_scores.jsonl` | baked into the image at build |
| AI hounds (`hound_bet`) | Fly volume, beside the app DB | `pack_settle.settle`, every 15 min (`ai_runner`) | same stores | baked into the image |
| House pack | `evidence/hounds_house_v1.jsonl` (git, in the image) | `pack_settle` in `scripts/capture_slot.sh` (CI), committed | same stores | git |

The image is rebuilt and redeployed hourly. The score store is filled by `src.pipeline.allsports_scores` from The Odds
API `/scores`, run by the capture slot (CI), then committed.

## The timeline (Hornets @ Nets, Odds API event `47cc511b...`, from `data/processed/allsports_scores.jsonl`)

| UTC | What happened |
|---|---|
| Oct 20 20:11 | NBA `/scores` poll (46 events). |
| Oct 21 04:49 | NBA `/scores` poll. |
| Oct 21 23:30 | Tip. The member's ticket is OPEN in the volume ledger. |
| Oct 22 00:10 | The ONLY NBA poll of the night: it needs a captured game an hour old, so it ran an hour into the games. It stored Hornets 21, Nets 15, `completed: false`. |
| ~02:00 | The game ends. Nothing is looking. |
| every 15 min | `user_settle` asks the image's score store: `completed: false`, so pending. |
| 06:00 | Owner's screenshots. |
| 08:10 at the earliest | `scores_poll_interval_hours = 8` (config/sports_catalog.json) blocks the next NBA poll until 00:10 + 8 h. Then a commit, then the next hourly rebuild: about 09:00-10:00Z, seven or more hours after the final. |

Root cause: a poll that fires mid-game followed by an 8-hour lockout, plus a score store that only reaches production by
commit and image rebuild. Nothing in production fetched a score itself.

## The fix

`src/hounds/live_settle.py` (loop in the API process, every 5 min, `LIVE_SETTLE`, default on) asks ESPN's free scoreboard
(MLB: the Stats API by gamePk) for only the games behind open tickets, caches the answer in `live_settle.db` beside the app
database, and runs the EXISTING `user_settle.settle` / `pack_settle.settle` with the live finals laid over their stores.
No grading rule changed. The watchdog (`check_grading`) alerts when a ticket is open 4 hours after its game's start.

## Not covered, on purpose

* **House pack tickets** are in git and baked in the image; the app cannot append to them. They still grade from the
  capture slot. The pages show their live state (the loop reads their games), and the watchdog does not count them.
* **Families with no live reader**: cricket, rugby, AFL, tennis, MMA, other basketball/hockey/soccer leagues not in
  `live_scores.ESPN_LEAGUE_BY_KEY`. They stay on the old path (and its 72-hour void). Adding one is one mapping line.
* **Soccer extra time and penalties** are not accepted from ESPN (books grade the match result at 90 minutes).
* **Percent-of-bankroll sizing** prints no per-ticket dollars (it compounds across bets); fixed sizing does.

## Expected delay now

A ticket grades on the first 5-minute pass after ESPN marks the game final: about 5 to 10 minutes after the final
whistle, 15 at the outside (one failed fetch costs one 1-minute backoff). Previously 7+ hours.
