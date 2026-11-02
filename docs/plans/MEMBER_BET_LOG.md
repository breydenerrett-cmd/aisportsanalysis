# Member bet log ("Log a bet") — plan, 2026-11-02

## Why
Jacob (comped member) has no easy way to record the real bets he makes. The old
My Bets screen (`api/mybets.py`, `src/appstate/savedbets.py`, `web/js/mybets.js`)
is not linked from any page, needs the game and side typed by hand, has no stake,
no live flag, and only grades MLB games by text match. It stays as-is (do not
delete; nothing links to it) and is superseded by this.

## What ships
A member can tap **Log a bet** on any game on the Live board or a game ticket,
pick the side, see the current average price filled in, type the stake, and save.
The bet is graded by the same path that grades hound bets (every sport we carry,
closing-line value, voids), and the member sees their own record beside their
hounds'. A fallback form logs a bet on a game that is not on our board (graded
by hand later: status "unmatched", never guessed).

Paper-or-real is the member's business: the copy says "your bets" and never
"paper". No advice, no edge/lock/beta words. Nothing is posted publicly; a
member's bets are private to that account (owner reads only through `_owned`-style
scoping; no public endpoint).

## Design (reuse, do not reinvent)
- **Ledger:** `src/hounds/member_bets.py`, append-only JSONL on the volume
  (`hounds_member_bets_v1.jsonl`, next to `hounds_user_v1.jsonl`). Row shape =
  the hound bet row (`user_engine` writes it: `event_id, sport, market, side, line,
  price_avg, price_best, n_books, commence_time, home_team, away_team, placed_utc,
  …`) plus `owner_user_id`, `stake_units` (0.25–10, member chooses), `live`
  (true when `commence_time` < placed time), `source: "member"`, `note` (≤140
  chars, optional), `hound_id: null`. Grades are appended as rows the way hound
  grades are, never edited in place.
- **Settlement:** `user_settle.settle(ledger=<member ledger>)` from the same
  15-minute `user_runner` pass. CLV via the existing `close_fn`. `alert=False`
  (a member knows what they bet; the alert feed is for hound bets).
- **Price fill:** the same board read `user_engine` uses for a hound's lock board
  (`_lock_board` / allsports view). If no price is on the board the field is
  empty and the member types one; a typed price must pass the betcheck
  plausibility bound (`api/betcheck.MIN/MAX_PLAUSIBLE_PRICE_MAGNITUDE`).
- **API** (`api/member_bets.py`, mounted in `api/app.py`):
  - `GET /me/bets` → `{bets:[…with grade, clv…], record:{w,l,p,units,stake_units,
    clv_mean,n_clv}, open:n}`
  - `POST /me/bets` body `{event_id, market, side, line?, price?, stake_units,
    note?}` → the row. Rate-limited like `/my-bets`. One side per game per
    member (same rule as hounds). 400 with a plain reason on anything else.
  - `POST /me/bets/manual` body `{sport, game_text, side_text, price?,
    stake_units, note?}` → row with `event_id: null, status: "unmatched"`.
  - `DELETE /me/bets/{id}` → void only while the game has not started;
    after that it stays (append a `voided_by_member` row, never delete).
  - Auth: `get_current_user`; any signed-in member, free or paid.
- **UI:**
  - Live board (`web/js/live-board.js`): a **Log a bet** button in each row's
    tray next to "Send a hound". Tap → side chooser (home/away, over/under,
    spread sides with the line) → price prefilled, stake input (default the
    member's last stake), optional note → Save. Live games show "In play" on
    the bet. Phone first, 16px gutters, no horizontal overflow.
  - Game ticket (`web/js/hounds-tickets.js` "Why this bet" fold): the same
    button, so a member can copy a hound's bet in one tap (prefills side+price).
  - **My bets** view: a tab in the kennel page (`web/kennel.html` + `kennel.js`),
    listing open bets on top, then settled with result, units, closing line,
    and a record line that sits beside the hounds' cards. Fallback **Log a bet
    by hand** form lives at the bottom of this tab.
  - Old `web/js/mybets.js` untouched.

## Workers (usage rule: Sonnet builders one at a time; Haiku for mechanical checks)
1. **Backend** — Sonnet builder, own worktree. Ledger, settle wiring, API, tests
   (`tests/test_member_bets.py`, `tests/test_member_bets_api.py`). Done when:
   place → settle → record works in a fixture with an NHL game, a tennis match
   and a total; a free member can place; CLV lands; a second side on the same
   game is refused; void before start works, after start refused; the member
   ledger is on the Fly volume path and in `.dockerignore`/Dockerfile rules
   (memory: served files must be in the image).
2. **UI** — Sonnet builder after 1 merges. Live board tray, ticket button,
   kennel tab, manual form. Tests through `tests/hounds_web_runner.py`
   (`tests/test_member_bets_web.py`), plus `test_kennel_page` and
   `test_no_horizontal_overflow`.
3. **Check** — Haiku runs the no-FastAPI harness + every test touching changed
   files; Fable reviews both diffs and does the live click-through as Brey's
   account after the hourly deploy (Log a bet on tonight's NHL game, see it in
   My bets, see it graded next morning).

## Not in scope
Public leaderboards of member bets, sharing, Twilio, parsing bet slips from
screenshots (later: a photo → fields fill, worth doing once the log exists).
