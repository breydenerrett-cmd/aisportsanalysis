# Backlog (kennel-first era, from 2026-10-21)

Parked owner requests and follow-ups. Highest priority first within each group. Move an item to a worker brief
when it starts; strike it when it ships.

## Product

| Pri | Item | Owner note | Added |
|---|---|---|---|
| LOW | **Live page redesign.** It is a plain list of game cards (sport chips, "Live now", "Next 24 hours", Send a hound). Make it feel alive: which of MY hounds are on each game, a live/now strip with game clocks and scores, hound avatars on the cards they're betting, a sport-grouped layout instead of 85 identical cards, a quieter "Send a hound". | "The screen looks pretty boring, low priority" (2026-10-21, screenshot of /web/live.html at desktop) | 2026-10-21 |
| LOW | Server-written copy without a viewer (Discord RSS, emails, share card, digest) still speaks in the $10 reference unit. | unit-sizing follow-up | 2026-10-21 |
| LOW | Gematria reveal offers "Backtest this", but a Gematria hound is forward-only. Hide or reword it for that style. | gematria-style checker | 2026-10-21 |
| LOW | Quiz Q3 at scroll 0 on a phone: the "Show me others" pill sits half under the tab bar until the user scrolls. | gematria-style checker | 2026-10-21 |

## Decisions waiting on the owner

- Desk hounds (pre-registered research arm, max 2 takes per game) can still take a both-lose pair. Block dead-zone pairs from a dated rule change?
- Trading-bot (separate project): the executor crashed with a Windows access violation (0xC0000005) at 16:05:11 ET on 2026-10-21 at session close. It was flat, so this was harmless. Hand it to that project's session?

## Ops

- Register `data/processed/batter_props.jsonl` (80.8 MB, ~0.5 MB/day) as rotatable before next MLB season. It will not reach 100 MB this postseason.
- Move the raw ESPN/UFC data out of the public repo into a private data repo (owner token steps needed).
- Windows-only test failures (exec bits, fcntl, rss, paths) and the hanging `test_daily_bootstrap` make a local full suite unreliable. Linux CI is the gate.
