# Pre-registration: the AI hounds

Committed before any forward bet. Written 2026-10-20. Code: `src/ai/` (the model layer),
`src/hounds/pack/ai_hounds.py` (the hounds), `src/hounds/ai_packet.py` (what a model is shown),
`src/hounds/ai_runner.py` (the schedule). Config: `config/ai_hounds.json`, `config/ai_providers.json`.
How to switch them on: `docs/owner/AI_KEYS.md`. Companion docs: `docs/PREREG_HOUSE_PACK_V1.md` (the rule
hounds whose runner and grading these reuse) and `docs/PREREG_HOUND_VERDICT.md` (the referee, unchanged and not
re-opened here).

Paper only. Nothing here places, sizes or routes a real bet. **No edge, profit or advantage is claimed, for
this hound or for AI hounds in general.** A language model reading a board is a hypothesis under test, the
same as every rule hound; a null result is as publishable as any other.

## 1. What is registered

| Hound id | Name | Category | Status |
|---|---|---|---|
| `ai_claude` | Claude Hound | `ai` | running when `AI_HOUNDS=on` |
| `ai_council` | Council Hound | `ai` | **parked** (`enabled: false`) until a second model is enabled |

The Claude Hound is one model, Claude Haiku 5.5 (`claude-haiku-5-5`), called through the official `anthropic`
SDK with `output_config={"effort": "low"}`, asked once per game. It is `who_decided: "model"`. It is not in the
21-hound rule pack (`pack.PACK`), which is unchanged.

The router (`src/ai/router.py`) is written for several providers and the config has a flag per provider, but
the free-tier and local adapters were not built: with one enabled model there is nothing to take a majority of,
which is why the Council is parked. Enabling a second model is a config entry plus an adapter, and a Council
that runs on it is a separate, dated decision; it does not alter the Claude Hound's registration.

## 2. What the model is shown (and the lock is the wall)

Asked about ONE game, at that game's lock (60 minutes before the start, the pack's `LOCK_MINUTES`), on the
same board the rule hounds use (`pack.base.build_board`: each book's newest quote at or before the lock, none
from the start on, none older than the sport's staleness window). The packet (`ai_packet.build_packet`) holds:

* the game: sport, the two clubs' names, Eastern date, start and lock times;
* for each market on the board (moneyline, spread, total): the main line, how many books quote it, per side the
  board-average price, the best price and its book, the book count and the consensus fair probability, and every
  book's own two prices on that line;
* how the moneyline's consensus moved from its first usable board (at least 60 minutes before the lock) to the
  lock, or a stated "no earlier board";
* each club's recent results from the stores the pack already reads: games, record, runs (or points) for and
  against per game, the last five results. MLB form counts games from 2026-08-28 only (the sealed window
  2026-01-01..2026-08-27 is never read), dated before the game and finished at least five hours before the lock;
* news: none. The packet has a hook for a news source and keeps an item only if it was observed at or before
  the lock, but **no news source is wired in this version**, and the packet says so.

It is never shown a person, an account, any hound's bet or record, an outcome, or a quote observed after the
lock. The router's prompt guard refuses to send a prompt containing an email, a phone number, a government id,
an API key or a configured secret. Tests pin all of this.

## 3. The answer, and the code rules

The model returns one JSON object: `decision` (bet or pass), `market`, `side`, `confidence` 1 to 5, `reason` of
25 words or fewer. It is validated strictly (`src/ai/schema.py`, `src/ai/decision.py`); nothing is repaired. An
invalid reply is retried once on the next provider if there is one, otherwise it is no answer.

Whatever the model says, code applies these rules (`pack_run`, the same runner as the rule hounds):

* **The -200 cap.** A bet whose board-average price is -200 or worse is never written. The price band is
  -199 to +400.
* The market must be on the lock board; one bet per hound per game; **at most 3 bets per hound per Eastern
  date**, taken in lock order; one unit paper stake (confidence does not change the stake).
* **One decision per hound per game.** A model is asked about a game at most once; the decision, bet or pass, is
  written to the decision log (`ai_decisions_v1.jsonl`, hash-chained) before anything else. A pass is final.
* **Any failure is a pass.** No key, over the monthly cap, cooling down after a 429, a timeout, a server error,
  an invalid answer twice: the hound passes and the reason is in the decision row. Nothing is retried later in
  the window, back-filled, or guessed.
* Every bet row carries `provider`, `model`, `confidence`, `latency_ms`, `cost_usd`, `prompt_version`, and
  `decision_hash` (the hash of the decision row it came from).

## 4. Forward only: no backtest, no drill, no replay

A language model has read about games that were already played. Replaying one over old boards would test its
memory, not its judgment, and would produce a record that means nothing. So an AI hound is only ever asked about
a game that has not started. This is enforced, not promised:

* `pack_run.run(..., replay=True)` raises `ForwardOnlyError` for any hound marked `forward_only`, before any
  model call;
* `python -m src.hounds.ai_runner --replay` is refused;
* the dog page's Backtest and drill (`drill.drill`) return `ai_forward_only` (HTTP 422) with the message
  "AI hounds are forward-only..." for an AI dog, and Ask's "earlier today" refuses it the same way;
* the AI hounds are not in `pack.PACK`/`BY_ID`, so the drill, the coach's hindsight and the learning loop's
  shadow cannot reach one by id.

`tests/test_ai_hounds.py` (`ForwardOnlyTests`) pins each of these.

## 5. The Council Hound (parked)

When enabled: it asks no model. For each game it reads the answers the model hounds logged and bets only when
at least `min_members` (3) of them returned a valid answer (bet or pass; a failed member is counted neither for
nor against) and a strict majority of the counted backed the same side (home or away, over or under), taking the
market most of the agreeing chose (a tie goes moneyline, spread, total). A bet nobody could place (off the board,
outside the price band) is not a vote. Exactly half is not a majority. Same price rules, same caps. Agreement
among models that are all one family reading one packet is not independent confirmation.

## 6. How they are graded

The same public record as every other hound, not a separate scoreboard: the AI ledger is registered as a house
ledger (`ledgers.Sources.default`), so the Claude Hound appears on `/hounds` in the `ai` category next to the
rule hounds, graded by `pack_settle`:

* WIN, LOSS, PUSH or VOID from the stored results; units at the **board-average price** (the owner's grading
  ruling), the best price shown separately;
* **CLV** against the close (the board just before the start, on the bet's own line): `100 x (close consensus
  fair - break-even of the average price)`;
* the referee's labels and its rule of 150 closing-line bets before any badge other than ROOKIE apply
  unchanged; units never decide a label.

Passes are not graded; they are counted and shown (decisions by reason) in the admin panel.

## 7. What would and would not count

Nothing is claimed in advance. The record will say what it says. Changing the prompt text, the model id, the
effort setting or any rule above is a new `prompt_version` (stamped on every decision row) and results before and
after are never pooled; a model or prompt change is announced by a dated edit to this file. No threshold is
changed after results are seen, and no result "rescues" a hound.

## 8. Cost and the cap

Haiku 5.5 is $0.10 per million input tokens and $0.50 per million output tokens (a prompt over 100,000 tokens
costs more; these prompts are about 1,500). A hound call is roughly $0.0002, so a 15-game day is a few tenths of a
cent. The router enforces a **hard monthly cap in code**: `AI_PAID_CAP_USD`, default 5. Before every paid call it
adds the call's worst case (prompt tokens estimated generously plus every output token allowed) to the month's
recorded spend, read from an append-only file on the Fly volume, and refuses if the sum passes the cap, so the
cap holds even for the call that would cross it. Non-urgent jobs (nightly recaps, hype lines) may use the
Message Batches API at half price; the worst case of a whole batch is reserved against the cap when it is
submitted and batch spend counts at 50%. A time-critical call (a pick before its lock) never uses a batch. The
Anthropic console's own spend limit (`docs/owner/AI_KEYS.md`) is a second wall.

When the model is capped, cooling down or down, the hounds pass and the panel says `degraded`. Ask calls no model
at all and keeps answering from the dog's own data; the sentence reserved for the case is "My AI brain is
resting, here's what my rules say."

## 9. Known limits

* The runner lives in the API process on Fly (the key lives there). Its odds store is the one baked into the
  image, redeployed about hourly, so a lock-time board can be built from quotes up to about an hour older than
  the capture slot's. The bet row records the average price, best price, book count and fair probability it used.
* A game that locks while the process is down, or before `AI_HOUNDS` is on, is never asked. Gaps are real and
  are not filled afterwards.
* Haiku 5.5 does not take a temperature, so the same prompt can return different answers. Each game is asked once
  and that one answer is the record.
* One model's reading of public information, with no news, is unlikely to see what the market does not. That is the
  hypothesis being tested, not a claim.
