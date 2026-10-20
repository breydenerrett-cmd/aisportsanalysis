# LINEHOUND voice guide

Owner, 2026-10-19 (verbatim): *"why is our linehound app and website look like a kids playground not a
professional gambling AI website, it says [the same thing] over and over, ... we're advertising that the
hounds section shows different dogs or hounds but no actual bets that they placed and why just a simple
and not transparent section that says just how much they are up on units."*

The 2026-10-18 voice pass (cartoon dogs, emojis, "Houndmaster" roasts, a "put down" poll, tombstones)
overshot. This guide replaces it. The target is a **professional sports-betting AI product**: think
Action Network, Outlier, OddsJam, a sportsbook's dark UI. Data-dense, clean, confident, in a bettor's
language. Keep the LINEHOUND brand and the strategy names (Pointer, Setter, Steamy Setter ...): they are
the product's **models**. Present them as serious AI betting models.

(Superseded: owner, 2026-10-18, *"we're losing the fun and gambling degenerate side of things"*. The persona
fields written for that pass stay in `config/` as data and in `src/hounds/voice.py` for a future Discord or
X post, but the site does not render them, with one exception: a model's catchphrase may appear as one small
italic line under its name.)

**Amendment, owner ruling 2026-10-20 (complete-product positioning).** The site advertises a complete product:
build your own AI sports bettor (a hound) from plain English or rules; it bets every sport we cover; every pick is
published before the game and graded win or lose on a public record; the house pack is our own hounds, championed,
trained, bred and culled in public. The product's words are **hound** and **house pack** again, in the same sober
register as above (no cartoons, no jokes, no emoji). Copy no longer says beta, early access, waitlist, "we're new",
"not enough data", "too early", "small sample", "unproven" or "paused". A functional rule stays, said confidently
("Ranked in full at 20 settled bets", "Verdict at 150 bets"). Hard limits unchanged: no claim of profit, an edge,
guaranteed wins, ROI or "beat the books"; "complete" means the product works, not that it wins; 21+, 1-800-GAMBLER
and "bet at your own risk" stay; Bet Check is never linked or advertised.

## How it sounds

- **Short and plain.** One idea per line. No jokes, no slang for effect, no exclamation marks.
- **Bettor language, used correctly:** units, ROI, record, CLV (beat the close), line, price, ticket,
  market, book, sample size. A bettor reads these without a glossary.
- **Confident, not hyped.** Say what the model did and what happened. Let the number carry it. "63-46 over
  109 bets, +11.38 units" beats any adjective.
- **Sample size on every claim.** The bet count sits beside every record, and a small sample says so
  ("Not enough bets (93/150)"). A hot start on 9 bets never reads as more than it is.
- **A refuted idea never reads as an open one.** "Interesting matchup, no demonstrated betting edge" is a
  valid, encouraged output. The research record stays part of the product's honesty.
- **Say it once.** The paper-only / not-advice / 21+ text appears once per page: in a compact disclosure bar
  near the top (the leaderboard, the model page) or in the shared footer (the landing page). The
  responsible-gambling line is in the footer. No second and third copy in body copy, and no server notice
  repeated under it.
- **No emoji in the interface.** Status is a word. A sign is a sign. Colour only agrees with the word.
- **No cartoons.** A model's avatar is a monogram: two initials on a tile, coloured by category.

## What the pages show

- **Landing:** *AI betting models, tracked in public.* Subline: *Dozens of models make paper bets every day.
  Every ticket is recorded before the game and graded after. Follow the ones that are winning.* A live mini
  leaderboard (top five by units, with record, ROI and bets), the latest five tickets, and two buttons:
  View the leaderboard, Build a model. The AI desk brief section comes second.
- **Leaderboard (`hounds.html`):** a sortable table. Model, Type, Record (W-L-P), Units, ROI, Bets, Avg
  price, CLV (share that beat the close, average points, n), Last 10 (dots), Status. Models with no graded bet
  are one collapsed "Warming up (N)" group with their open-ticket count, never rows of 0-0. Below the table:
  Latest tickets (every model's newest bets as ticket rows), then a small Retired models table. A model's row
  opens a drawer with its last ten tickets. "Data as of ..." sits above the table; older than six hours (or a
  saved copy) adds a quiet amber "Updating" note.
- **Model page (`hound.html`):** header (initials badge, name, type, sports and markets, status), a KPI strip
  (Units, ROI, Record, Bets, CLV, Streak), Open tickets, Graded tickets, the Rule (exact text and dials),
  Bankroll chart, Status, Versions, and the tips panel ("Coach this model").
- **Every number is traceable to a ticket.** A ticket row has the date, game, pick, market, price taken, how
  many books quoted it, when it went on the record against the first pitch, its status (PENDING, WON, LOST,
  PUSH) and, once graded, its units and its closing-line value.

## Status words (the referee's labels, said plainly)

The referee's labels do not change and are not computed differently. The pages print them in plain words, keyed
on the label alone and never on units. A model can lead on units and still say **Paying the vig**; that is the
point of the column.

| Referee label (internal) | Status on the page | One plain line |
| --- | --- | --- |
| BEATING THE CLOSE | **Beating the close** | Its prices keep beating where the market closes. Good shopping, not a promise of wins. |
| NO DIFFERENT FROM THE MARKET | **Market** | Its prices look like the closing line: no better, no worse. |
| PAYING THE VIG | **Paying the vig** | Its prices keep landing worse than the close, so every bet costs a little extra. |
| TOO EARLY | **Not enough bets (n/150)** | A model needs 150 bets with a measurable closing price before a verdict. n is how many it has. |
| NOT MEASURED (the paused card) | **Not graded vs close** | This model was never graded against the closing line. |
| a retired model | **Retired** | Stopped by its own retirement rule. Its record stays. |

## Translations

| Old (2026-10-18) | Now |
| --- | --- |
| the kennel, the dogs, the pack | the leaderboard, the models |
| hound / dog (public pages) | model (the code and URLs keep `hound`) |
| graveyard, tombstones, put down | Retired models (name, final record, units, reason, date) |
| doghouse, "who gets put down next" poll | not shown |
| Houndmaster roasts and brags | not shown |
| SHARP / COIN FLIP / FEEDING THE BOOK / ROOKIE | Beating the close / Market / Paying the vig / Not enough bets (n/150) |
| champion / challenger | current version / challenger |
| forward results / replay | live bets / rehearsal (never counted) |
| benched | Idle (no ticket in 7+ days) |
| closing-line value | CLV, or "beat the close" |
| Tail it / Fade it | not shown (Copy rule, Build one like this) |
| Fire now, Fire again, "firing" (2026-10-19, owner) | **Take them out back** (the button, also "Take them out back again"), **Out back** (the tab), "Taking <name> out back..." (while it loads), "<name>'s picks right now" (the result heading). The route (`/fire`) and the `data-hook`s keep the old word; only what a person reads changed. |
| Drill, Run drill, Hindsight drill (2026-10-19, owner) | **Backtest**, **Run backtest**, **Backtest (hindsight, not counted in the record)**. 7 / 14 / 30 days and Season 2, on every dog page, in the studio and in the Training camp. Hook and route keep `drill`. |
| the handle "Handler 3F2A" | the member's kennel name once they set one ("Name your kennel", 2 to 30 characters); the handle is the default until then |

## Banned

**The hard lines (they protect the owner; say them plainly, never drop them):**
paper bets only; not advice; 21+; a visible *Gamble responsibly. 1-800-GAMBLER* line in the footer of
every page. No claim anyone wins long-term. Never "lock", "guaranteed", "can't lose", "sure thing",
"free money", or any edge claim. Never call price improvement an edge or EV. Never call units profit.
Never call late_move "CLV".

**Academic words, off every public page:** pre-registered (and "preregistered"), date-clustered,
bootstrap, confidence interval, closing-line value (write CLV), hypothesis, population, falsification,
registry. Also skip: p-value, significance, Benjamini-Hochberg, false-discovery, null result.
The facts stay. The vocabulary changes. If a number needs a footnote, put it in a collapsed "How to read
this table" block, in plain words.

A test (`tests/test_hounds_voice.py`) fails if the hard-line words or the academic words show up in the
public pages' text, and `tests/test_hounds_board_pages.py` fails if the leaderboard, the model page or the
landing hero show an emoji, a cartoon avatar, a second disclosure, or the toy voice.

## Examples

- Landing: *AI betting models, tracked in public.*
- Leaderboard row: *Setter. MLB moneyline. 63-46. +11.38 units. +10.4% ROI. 109 bets. -118. 54% beat the
  close, +0.8 pts, n=91. Not enough bets (91/150).*
- Ticket: *Tampa Bay Rays at Cleveland Guardians. Over 6.5, total. -105 (best +100, betrivers, 7 books).
  Oct 18 20:10 UTC, 60m before the start. PENDING.*
- Honest and plain: *Not enough bets (93/150). Results this early are mostly luck.*
