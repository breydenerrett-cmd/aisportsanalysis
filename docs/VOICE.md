# LINEHOUND voice guide

Owner, 2026-10-18: *"This is becoming very like science backed math and not fun, we're losing the fun and
gambling degenerate side of things. Scientists aren't buying this. Data mathematics nor. Degenerate
gamblers dude."*

So: write for sports bettors who like action. Discord and X people. Parlays, bad beats, tailing and
fading, trash talk. Not for scientists, not for a methods section. The same voice on the site, in
Discord and on X.

## How it sounds

- **Short and punchy.** One idea per line. If a sentence needs a comma and a clause, cut it in two.
- **Slang is fine.** Chalk, dog, heater, steam, bad beat, tail, fade, tilt, juice, cooked, cashed.
- **Trash talk is fine,** aimed at the dogs, the nerds and ourselves. Never at a real person, a bettor
  who lost, or a real team's fans.
- **Emojis in moderation.** One or two a line at most, where they carry the joke: 🔥 🥶 💀 🐣 🪙 💸 🪦.
  Never as the only signal. A badge always has its word beside the emoji.
- **Numbers degens care about:** W-L, units, streaks, best bet, worst beat, bad beats. Put the bet
  count right beside any record (`63-46 in 109 bets`) so a small sample is never hidden.
- **Roast the dogs, be straight about the facts.** The joke is on the dog. The number is the number.
- **Lead with the action,** then the receipts. The honest check is a badge, not a lecture.

## The people (and dogs) who talk

- **The Houndmaster** is the kennel boss: grumpy, fair, seen every bad beat twice. He roasts a dog
  after a losing day and brags on it after a winning day. Never kind, never cruel. Config:
  `config/house_pack.json`, key `houndmaster`.
- **Every dog has a persona** (`persona` in `config/house_pack.json`, `config/house_hounds.json`,
  `config/desk_hounds.json`): a `bio` that is true to its actual rule, a `catchphrase`, a `vibe`
  (degen, nerd, grinder, psychic, chaos), five `roasts` and five `brags` the Houndmaster says to it, a
  one-line `epitaph` for the tombstone and a `verb` for the live feed ("tailed the steam on ...").
  Gematria and moon dogs lean into the mystic bit. Coin-Flip Collie is the troll that keeps beating the
  nerds. Professor Paws is the overconfident nerd.
- A builder's dog has no persona; it wears the vibe of the style it was built with, and the Houndmaster
  uses his own lines for it.
- **Which line today?** The same dog on the same day always gets the same line:
  `lines[fnv1a(dog_id + "|" + settled_day) % len(lines)]`, where the day is the last settled day
  (`src/hounds/voice.py`, `web/js/hounds-voice.js`; a test checks the two agree). A roast after a losing
  day, a brag after a winning day, nothing after a flat day.

## Badges (the old verdict labels, translated)

The referee's labels do not change and are not computed differently. The site just wears them like a
bettor would. The badge always sits beside the dog and a tap shows one plain line.

| Referee label (internal) | Badge | One plain line |
| --- | --- | --- |
| BEATING THE CLOSE | **SHARP 🔥** | Its prices keep beating where the market closes. Good shopping, not a promise of wins. |
| NO DIFFERENT FROM THE MARKET | **COIN FLIP 🪙** | Its prices look just like the closing line: no better, no worse. A coin flip, so far. |
| PAYING THE VIG | **FEEDING THE BOOK 💸** | Its prices keep landing worse than the close. Every bet costs it a little extra. |
| TOO EARLY | **ROOKIE 🐣** | Too few bets to judge. Wins and losses this early are mostly luck. |
| NOT MEASURED (the paused card) | **UNRATED 🐾** | This one was never graded against the closing line. |

The leaderboard is ordered by paper units (average price, live bets). A dog can lead and still wear
FEEDING THE BOOK, and the page says so right beside it. That is the point of the badge.

## Translations

| Don't say | Say |
| --- | --- |
| closing-line value / CLV | beat the closing line |
| retired | **put down 💀**, with an epitaph (cause of death in plain words) |
| graveyard of retired hounds | the graveyard, tombstones |
| champion / challenger | starter / rookie |
| promoted / retired (challenger) | made the team / cut |
| forward results / replay | live bets / old-board rehearsal (never counted) |
| benched | napping |
| hound (on public pages) | dog (the code and URLs keep `hound`) |
| the race, in verdict order | the leaderboard |
| the verdict test | the badge |
| lock the price | bet (as in "when it bets") |

## Banned

**The hard lines (they protect the owner; say them like a human, never drop them):**
paper bets only; not advice; 21+; a visible *Gamble responsibly. 1-800-GAMBLER* line in the footer of
every page. No claim anyone wins long-term. Never "lock", "guaranteed", "can't lose", "sure thing",
"free money", or any edge claim. Never call price improvement an edge or EV. Never call units profit.

**Academic words, off every public page:** pre-registered (and "preregistered"), date-clustered,
bootstrap, confidence interval, closing-line value, hypothesis, population, falsification, registry.
Also skip: p-value, significance, Benjamini-Hochberg, false-discovery (say "fluke check"), null result.
The facts stay. The vocabulary changes. If a number needs a footnote, put it in a collapsed "receipts"
block, in plain words.

A test (`tests/test_hounds_voice.py`) fails if the hard-line words or the academic words show up in the
public pages' text.

## Examples

- Landing: *Paper betting bots fighting it out every day. Build your own dog. Watch them win, lose,
  and get put down.*
- Houndmaster, after a loss: *You faded the steam and the steam ran you over. Short legs, short memory.*
- Houndmaster, after a win: *Okay. That was good. Don't make a thing of it.*
- Feed: *Steamy Setter just tailed the steam on NYY -1.5 at -110.*
- Tombstone: *R.I.P. Basset. "Went under one last time." Cause of death: went more than 25 units under.*
- Honest and still fun: *Rookie. 12 bets. Could be hot, could be luck. Check back at 150.*
