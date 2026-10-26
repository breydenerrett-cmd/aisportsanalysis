# The hound loop: making the app feel guided, not random (owner ask, 2026-10-26)

Owner: "we need a much better rules editor, sports selection, track record page... it should feel like the app is always trying to keep people investigating, researching, making or taking bets based on hounds, backtesting; it feels chaotic and random right now."

## The loop every screen serves

**Find → Check the record → Test → Build or copy → Unleash → Review**, then back to Find.

- Every screen has ONE clear next step pointing to the next stage of the loop. That step is the primary button; anything else is secondary or sits in a ⋯ menu.
- Nothing ends in a dead end: an empty state always says what to do next ("No games tonight in MLB, add NBA").

## Phases (one Sonnet builder at a time, shipped after each)

1. **Hound page redesign**: in progress.
   - Hero with the full name and status line.
   - Open tickets shown alongside settled ones; an off-season note.
   - Remove moves to the ⋯ menu; scrollable tabs.
   - Unleash is state-aware; Backtest runs automatically; Rules shows the current rule first.
2. **Rules editor and sports selection.** The editor becomes a step-by-step builder instead of a blank text box:
   - **Sports:** chips showing what's in season and how many games are in the next 7 days ("NBA · 58 games this week", "MLB · postseason, 3 games"). Out-of-season sports are dimmed with a reason.
   - **Markets per sport:** moneyline, spread, total, props where we have them.
   - **Conditions:** plain-English blocks with sliders (form, rest, home/away, line move, gematria).
   - **Price range:** one slider with the -200 floor drawn in.
   - **Limits:** bets per day and stake.
   - **Live preview:** "Over the last 14 days this rule would have bet 23 times: 13-10, +2.1u (hindsight)". It updates as the member edits.
   - "Say it in words" stays as a shortcut that fills in the steps, so it is never the only way in.
3. **Track record page.**
   - **Header:** record, units, ROI, average closing-line value, a bankroll curve and the current streak.
   - **Breakdowns:** by sport, market, price band, favourite vs underdog, and home vs away, from the existing diagnosis code. Each comes with "what's working / what's not" in plain words.
   - **Results calendar:** win and loss days.
   - **Ticket list:** filterable, each ticket with its "why".
   - **Compare:** against the house pack and the leaderboard average.
   - **Next steps:** "Backtest a tweak", "Copy this hound", "Ask why it lost".
4. **Guided flow, tying it together:**
   - **A "Tonight" home** (signed-in): your hounds' bets tonight, top hounds' bets you can tail (paper), games your hounds are checking and when, and a "your hound went 2-1 last night" recap.
   - **Next-step prompts at the end of every flow:** after creating → Backtest 30 days → Unleash; after a loss → Ask why / Retune; after viewing a top hound → Copy it.
   - **Tab bar:** Tonight · Hounds (leaderboard + discover) · My Kennel · Live · Account. "Create" moves to a + button in My Kennel and on Hounds.

## Guard rails (unchanged)

- Paper only; no profit claims.
- No -200 or worse.
- Never "dog" in user-facing copy.
- Hindsight backtests are always labelled and never counted toward the record.
- Times in the viewer's zone.
