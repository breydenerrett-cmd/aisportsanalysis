# The Kennel Room

A small animated room where every hound is a character, and what it is doing in the room is what it is doing in the record. It is display
only: it reads the endpoints the product already has and never writes. Adapted from the Edge Desk's "Floor" (a pattern, not a copy: that
domain was trading bots, this one is paper sports-betting hounds). Owner rulings behind it: `docs/design/KENNEL_FIRST_BRIEF.md`,
`docs/VOICE.md`.

**The rule that matters most: the animation reflects real state only.** A hound is never shown at its desk without an open ticket, never
scouting without a board that was read, never celebrating without a graded win. Where the data cannot say, the room says less.

- **Pages.** `web/room.html` (the public house kennel: the house pack plus the Claude Hound; the landing page's "Betting right now" strip
  links to it) and "Your kennel room", a collapsible block at the top of `web/kennel.html` (My Kennel, signed in only).
- **Code.**
  - `web/js/room-adapter.js`: input rows -> character states. Pure (no DOM, no fetch, no clock of its own); also runs under node.
  - `web/js/room-data.js`: the requests only. It assembles the adapter's input and decides no state.
  - `web/js/room-layout.js`: where each hound stands (the zone bands, the seats across, the rows, "+K more", who is drawn first) and where its
    label (pick bubble, settled units) sits: one line, two heights for neighbours, slid whole into the slice a phone shows. Pure (runs under node).
  - `web/js/room-scene.js`: draws the room and the hounds (pure SVG / CSS / DOM, no image file, no `innerHTML`), the card, the roster, polling,
    sound. `mountRoom` (the public room) and `mountKennelRoom` (the fold).
  - `web/css/room.css`, `web/js/room-page.js` (the 3-line boot of `room.html`).
- **The hounds are the product's own art.** `dogFace()` from `dog-avatar.js` (the same illustrated hounds as the kennel cards and the
  leaderboard), so each hound looks like itself. The pose comes from the state (`POSE_OF`), the look from the hound's saved look.
- **Tests.** `tests/test_kennel_room.py` (adapter fixtures under node, the room rendered in the node harness's fake DOM, static checks),
  plus `room.html` in `tests/test_kennel_page.py` PAGES and `tests/test_no_horizontal_overflow.py`.

**Who is in the public room.** Every hound `GET /hounds` serves with `kind` `house`: the house pack, the Claude Hound, and the Gematria Hound
(`numerology_newfie`) whenever the pack carries it. The room adds none and hides none; nothing is hard-coded by name.

## Data (in this order, all soft: a failure leaves that part empty and the room claims less)

| Room | Request | Gives |
|---|---|---|
| House | `GET /hounds` (kind `house`) | the hounds: record, units, status, sports, open-ticket count |
| House | `GET /hounds/stream?page_size=100` | the newest tickets of every hound: the open ones and the recently graded ones |
| House | `GET /hounds/graveyard` (once every 10 min) | the headstone count for the corner stone |
| Kennel | `GET /hounds/kennels/mine` (or the payload My Kennel already holds) | the member's hounds (buried ones are not in `dogs`; `graveyard` holds their headstones) |
| Kennel | `GET /hounds/{id}/bets?status=open` / `?status=graded` | open tickets / recently graded tickets, one request per hound that has any |
| Both | `GET /sports/now` (a signed-in viewer only: the route needs an account) | today's board, for scouting |

**Today's board** is the games live now plus the games still to start on today's slate date (US Eastern, the calendar the boards are keyed
by), counted by sport code. Tomorrow's games are not counted, so a hound that finished its day naps instead of scouting tomorrow all night.
A signed-out visitor has no board: `board` is `null`, and **an unread board never claims scouting** (the hound naps as "No open pick").

**Polling.** Every 45 s (`POLL_MS`); the timer is cleared while the tab is hidden and the room refreshes at once when it comes back (if the
last read is over 30 s old). A folded "Your kennel room" stops polling until it is opened. A failed poll keeps the last good picture and says
"Could not refresh. Showing 4:05 PM." A server still warming up is said plainly and retried once after 6 s.

## The room (tap targets)

| Object | Opens |
|---|---|
| A hound (or its name in the list under the room) | Its card: state, the open pick, record with the settled count, units, open tickets, the last settled result, a small-sample note under 10 settled, and **Open hound page** (`hound.html?id=...`). In My Kennel it adds **Open studio**, **Unleash** and **Edit rules** (the studio's own tabs, `kennel.html?dog=<id>&tab=look|fire|rules`; on My Kennel they open the drawer in place) |
| The whiteboard (left wall) | `hounds.html`, the Leaderboard. It shows the top three by units among hounds with enough settled bets |
| The TV (back wall) | `live.html`, Live. It shows the real counts: open tickets, hounds with a game live, games left on today's board |
| The door | `kennel.html`, My Kennel |
| The bulletin board | A placeholder for the daily recap: it opens a card that says "No recap pinned yet." It links nowhere |
| The headstone in the corner (only when there is one) | `graveyard.html`, with the count |

## State mapping

The adapter evaluates these rules top to bottom for every hound. The first match wins.

| # | Condition | State | Zone | What you see |
|---|---|---|---|---|
| 0 | `status` is `buried` | not in the room | corner stone | A small headstone in the corner links to the Graveyard. (`/hounds/kennels/mine` already leaves buried hounds out of `dogs`; their headstones arrive as `graveyard` and set the count.) |
| 0 | `retired`, or `status` is `retired` | not in the room | none | A retired model has left. Its record stays on the leaderboard |
| 1 | `status` is `training`, or its newest version came from a training (`trained_times > 0` and `coached_from`) and it has no settled bet and no open ticket | `training` | gym | "At the gym": a whistle, the dog doing reps. "Fresh from training. Its new record starts now." |
| 2 | An open forward ticket (`status` OPEN, not a refusal, not a replay), or the hound's own `open_bets` is above 0 | `pending` | its desk | At its desk on the phone, bubble `Celtics ML +130 · 1u` (the soonest-starting open ticket, `+N more` for the rest). Label **Game live** when any open ticket's first pitch has passed, else **At its desk** |
| 3 | Graded forward tickets inside the recent window (`graded_utc`, else first pitch + 3 h) with a net above 0 | `won` | its desk | Jumps, confetti, `+1.3u` floats up (the net units of the window), pose `celebrate` |
| 4 | The same, net below 0 | `lost` | water bowl | A rain cloud with `-1u` written on it (it does not float, so it never drifts up over the TV), walks to the bowl, pose `sad` |
| 5 | Status `running`, a board that was read, at least one game on it in the hound's sports, no open ticket, and not the viewer's night | `scouting` | open floor | Paces and sniffs. "N games left on today's board in its sports. No pick yet." |
| 6 | Otherwise, and the viewer's local hour is 23:00 to 05:59 | `asleep` | bed | Dimmed, curled, floating z's |
| 7 | Otherwise | `nap` | bed | In the dog bed, one of: **Idle** (`benched`: no ticket in 7+ days), **Not started**, **Resting** (any other non-running status), **No open pick** (the board was not read), **Done for today** (it bet today and the board is empty), **No games left** |

Notes on the rules:

- **Recent window.** `RECENT_HOURS = 4`. The bet rows the API serves carry no graded time (`BetRow` has `start_utc` and `recorded_utc`, not
  `graded_utc`), so today every settle time is **estimated** as first pitch + 3 hours (`GAME_HOURS`), and the card says "(time estimated)". If a
  row ever carries `graded_utc`, that is used instead. A ticket with neither stamp is never dated, so it never triggers a celebration.
- **Net.** Several results inside the window net out: 1 win at +1.3u and 1 loss at -1u is a win of +0.3u (`1-1`); an exact wash is neither.
  Pushes and voids never celebrate.
- **An open pick beats a recent result** (the kit's order, trade before win). The result stays on the card as "Last settled".
- **Overnight is the viewer's local clock** (`localHour`), not Eastern. A pick still open after midnight keeps its hound at its desk.
- **Training is honest about what the product has.** There is no long-running "training" status: Send to training makes the next version at once
  and its record starts now. The gym is therefore shown for the hound that is fresh from training and has not bet yet, and for an explicit
  `status: "training"` if the API ever sends one. It never claims a training is in progress otherwise.
- **-200 or worse is never put in a bubble.** A price of -200 or worse, or the row's own `beyond_cap` flag, shows `Open ticket` with no pick
  and no price (the product recommends none).
- **Stake** is the row's `stake` / `stake_units`, else the hound's `bankroll.stake_units`, else `1u`.
- **Sports.** A hound's sports match the board by code (`MLB`, `NBA`...); an empty list, `dog_menu`, `all` or `any` means every sport.

## Badges

- **Crown: the season leader.** The most units (`record.units_average_price`, ties by settled bets) among the room's hounds with at least
  `min_ranked_bets` settled (the season's own number, else 10) and units above zero. No ranked hound means no crown. A leader who is down gets none.
- **Trained xN.** A small `x2` tag on the dog and the product's own "Trained x2" chip on the card, from `trained_times`.
- **Season leader** chip and **Live** dot (a game is live) are the only other marks.

## Behaviour

- **Movement.** A state change walks the hound to its new zone (a 2.4 s `left` / `top` transition). Hounds keep their seat while they stay in a
  zone and the seat still exists. The hound elements are kept between reads, so a move is a transition and not a redraw.
- **Crowding: the room scales from 0 to 40 hounds** (`planRoom` in `room-layout.js`; `RoomCrowding` and `PlanTheRoom` in `tests/test_kennel_room.py`).
  The real pack is 35 hounds with the Claude Hound and the Gematria Hound; the first version had twelve desks, four floor seats and eight spare
  places, which overlapped at that size (hounds on each other, names colliding, the scouting row running into the GYM).
  - **Zones are bands, top to bottom:** the floor (scouting), the water bowl (just lost), the desks (an open pick, just won), the gym (fresh from
    training), the beds (naps, sleep). A band is the full width of the room. Only the desks and the beds are always drawn (an honest empty room shows
    empty desks and beds); the others appear when a hound is in them. The GYM and BEDS signs are the first thing in their band, above the first row.
  - **Seats across follow the stage's width** (`columnsFor`): as many as fit at 108 px or more each (7 on the 860 px a phone pans inside, 8 at 1000,
    9 at 1124, never more than 10). Seats are `890 / cols` view units apart.
  - **A zone with more hounds than seats wraps into more rows**, at most 3 (floor, beds), 2 (desks), 1 (bowl, gym), and the room gets taller (the
    stage's `aspect-ratio` is set from the rows; 600 view units is the least). Past that the zone shows its first N and its last seat is
    **"+K more"**, a button that lists that zone's hounds in the status list under the room ("On the floor: 14 of 35", with **Show everyone**).
    The list always holds every hound, from the same adapter state; only the first N are drawn.
  - **Who is drawn first** (`orderCharacters`): the season leader, then the most recent activity (a settled result, newest first; then a game that is
    live; then the soonest first pitch among open tickets), then the most open tickets and settled bets, then name and id, so the same input always
    gives the same room. A hound keeps its seat while it stays visible in its zone; a new one takes the first free seat.
  - **Nothing can overlap.** Rows are 112 to 172 view units apart (a hound is at most 92 tall, its crown 16 more; a desk row leaves room above for both
    heights of a bubble), seats are a whole seat apart, bands never share a place. A name tag is a seat less 18 px wide (a pacing hound sways 6 px) and
    truncates with an ellipsis, the whole name in its `title`. A bubble is at most two seats less a gap (`labelMax`, and no wider than the room at the
    end seats), so labelled neighbours alternating on two heights can never touch. On a phone, labels that cannot stand side by side inside the visible
    slice share it (`--rm-fit`; the pick is cut with an ellipsis, `+N more` never).
  - **Each zone's boundary is an invisible rect** (`rect.rm-zone[data-zone]` in the room's SVG); the render check measures every sprite, name tag,
    bubble, units float, "+K more" and sign against it and against each other.
- **Labels.** A pick bubble is one line: the pick truncates with an ellipsis (the card has it whole), `+N more` never does. Labelled neighbours in
  a row take turns on two heights (assignTiers, from the labels' measured widths), so two labels at one height are two seats apart. On a phone a label of a
  hound in view slides sideways until it is whole inside the visible slice (and clear of the label beside it); a label whose hound is out of view and
  would be cut by the edge is not drawn. The settled-units float on a win moves a few px, not up the wall.
- **Zones read at a glance.** The GYM sign sits at the top of the gym band, on the gym mat; the BEDS sign at the top of the beds band. Napping hounds
  settle into a bed. `data-zone` and `data-label` on each hound and on each list entry come from the same adapter state, and
  `tests/test_kennel_room.py` (`ZoneAndListSayTheSame`) pins it.
- **Phone first.** The stage keeps a minimum width (860 px) inside its frame and pans there (the frame, not the page, scrolls sideways); it
  opens centred on where the hounds are. Under it, a list of every hound with its state (a tap opens the card) is the phone's main way in
  and the screen reader's. The page never scrolls sideways (`tests/test_no_horizontal_overflow.py`, 390 px).
- **Reduced motion.** Every animation and transition sits inside `@media (prefers-reduced-motion: no-preference)`. Reduced motion keeps each
  state's static pose and props: the cloud, the confetti, the `+1.3u`, the z's, the whistle, the bubble.
- **Sound.** Off by default and not remembered. "Sound on" plays a short tone only when a hound's state **changes** to won or lost between two
  polls (a first load is silent). WebAudio synthesis, no files.
- **My Kennel fold.** Open on a wide screen, folded on a phone, until the member chooses (kept in `localStorage`, `linehound.kennel-room.open`, in a
  try/catch). A member with no active hound has no room. A public kennel (`?u=`) has none. It carries no paper line of its own (the page has one).
- **Text.** Every string is set with `textContent`; nothing a hound is named reaches markup. A name truncates with an ellipsis inside its tag (a seat less 18 px; the tag's `title` and the card have it whole).
- **Copy.** No emoji, no profit or edge words, no Bet Check. One short paper line under the public room ("Paper bets only. Units are the
  scoreboard, not money.") and the compliance footer once (21+, paper bets, bet at your own risk, `tel:` 1-800-GAMBLER).

## Known gaps

- No bet row carries a graded time, so "just won/lost" is dated by first pitch (labelled estimated). Adding `graded_utc` to `BetRow` makes it exact; the adapter already prefers it.
- A signed-out visitor sees no scouting (the board route needs an account). Idle hounds nap as "No open pick".
- The bulletin board is a placeholder until the daily recap exists.
- There is no live "training" status; the gym shows the fresh-from-training hound (see above).
