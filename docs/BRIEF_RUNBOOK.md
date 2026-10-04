# Running a matchup brief (session-assisted)

This delivery is session-assisted, not unattended: a Claude Code session must be open. It
becomes unattended only when the owner adds the API key (`docs/decisions/AI_ANALYST_ENABLE.md`)
and a scheduled run has been proven.

## Resume command

In a Claude Code session in this repository, say:

```
run the brief
```

That means the steps below, for the next MLB game that has not started. Nothing has to be
remembered from an earlier session; the steps are complete.

## Steps

1. Bring this computer's stats current (they are not committed and go stale):
   `python -m src.pipeline.display_refresh --max-seconds 400`
   Do not commit the refreshed files under `data/historical/`.
2. Pull the latest captured prices: fetch and merge the working branch.
3. Pick the game (see "Which game" below) and freeze it:
   `python -m src.cli analyst pilot prepare --date YYYY-MM-DD --game AWAY@HOME`
4. A Sonnet subagent, given only `request.json` from the folder that command prints, writes
   `answer.json` there. It reads no other file and uses no outside knowledge.
5. Check it: `python -m src.cli analyst pilot check --dir DIR --response DIR/answer.json`.
   Read every call against the frozen quotes: event, player, market, line, side, price, book.
   If the summary is withheld or a call is struck for a fixable reason (for example a number it
   computed without declaring it), have the subagent answer again; never edit the answer by hand.
6. Publish within 90 minutes of step 3 and before first pitch:
   `python -m src.cli analyst pilot publish --dir DIR --response DIR/answer.json --model claude-sonnet-5-5 --tokens-in N --tokens-out N --seconds S --operator-minutes M`
7. Point the public sample at it: set `config/sample_brief.json` to `{"date": ..., "away": ..., "home": ...}`.
8. Commit the pilot ledger, the packet folder and the config by path; push in the minute 15 to 39
   window; check `/sample/brief` on staging, then production after its hourly refresh.
9. Verify both views: the public page `/web/sample.html`, and the signed-in game page as a tester.
10. After the game: `python -m src.cli analyst grade --date YYYY-MM-DD`, commit, push.

## Which game

Take the next game by first pitch that meets all of: it has not started; `prepare` does not print
SKIP (it has captured prices); both listed starters are known. Freeze about 2.5 hours before first
pitch, when the lineup and prop prices are usually in; freezing earlier is allowed and the brief
then lists what was missing.

Fallback, in order, if the planned game cannot be used or its window was missed:
1. the next game the same day;
2. the first game of the next day, frozen the evening before with what exists;
3. a brief made only of passes is still a brief: it explains the matchup, compares the markets,
   gives the strongest case each way and says what would change the call. Never force a bet.

One missing price feed does not stop the brief: a market with no price is listed as missing and
the other markets are still called.

## What never happens

No brief is published after first pitch. No call is edited after publishing; a correction is a
new published version. Nothing here turns billing on or sends a message to anyone.
