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
2. Pull the latest captured prices: fetch and merge the working branch. Then bring today's posted
   lineups current (the capture may have run before a club posted; on 2026-10-04 the packet held
   one club's nine and did not list the other as missing):
   `python -c "from src.pipeline import lineup_store; print(lineup_store.build(['YYYY-MM-DD'], refresh=('YYYY-MM-DD',)))"`
   After `prepare`, confirm both lineups are in `packet.json` before spending a session on it.
3. Pick the game (see "Which game" below) and freeze it:
   `python -m src.cli analyst pilot prepare --date YYYY-MM-DD --game AWAY@HOME`
4. A Sonnet subagent, given only `request.json` from the folder that command prints, writes
   `answer.json` there. It reads no other file and uses no outside knowledge.
5. Check it: `python -m src.cli analyst pilot check --dir DIR --response DIR/answer.json`.
   Read every call against the frozen quotes: event, player, market, line, side, price, book.
   If the summary is withheld or a call is struck for a fixable reason (for example a number it
   computed without declaring it), have the subagent answer again; never edit the answer by hand.
   Give the subagent no hint about which way to lean: the instruction is the request and nothing
   else. Checker rejections seen so far, all fixed by the writer answering again: a banned word
   ("edge"), a number it computed without declaring it, its own estimate quoted in the summary, and
   a name written differently from the packet ("San Diego's Morejon", "two Braves"), and a price
   that is not in the data ("-200" as the limit). When the writer answers again, give it the
   checker's rejection lines and nothing else. A struck call is published as a pass marked "could
   not be verified"; if time before first pitch is short, publishing with one struck pass is
   allowed and is recorded in the ledger.
   Seen 2026-10-04: two answers to the same frozen data differed (one took a strikeout prop, the
   next passed on everything). The published answer is the one that cleared the checker; the
   call is not stable across answers, so say "one model reading", never "the model's view".
   A later version of the same game (lineups now posted): copy the folder aside first, `prepare`
   again, and publish with `--refresh`; the earlier version stays in the ledger.
6. Publish within 90 minutes of step 3 and before first pitch:
   `python -m src.cli analyst pilot publish --dir DIR --response DIR/answer.json --model claude-sonnet-5-5 --tokens-in N --tokens-out N --seconds S --operator-minutes M`
7. Point the public sample at it: set `config/sample_brief.json` to `{"date": ..., "away": ..., "home": ...}`.
8. Commit the pilot ledger, the packet folder and the config by path; push in the minute 15 to 39
   window; check `/sample/brief` on staging, then production after its hourly refresh.
9. Verify both views: the public page `/web/sample.html`, and the signed-in game page as a tester.
10. After the game: `python -m src.cli analyst grade --date YYYY-MM-DD`, commit, push.

## Answering a prepared game: the publication rule (in force from 2026-10-05, enforced by code)

The first answer is the candidate. Nobody picks among answers.

1. The writer answers from `request.json` and nothing else. Run `pilot check` on the file; that
   records attempt 1 in the folder (`attempts.jsonl`, `attempt_1.json`).
2. If check is clean, publish it. Do not write another answer "to see if it differs": an answer
   that follows a clean one is a reroll and `pilot publish` refuses it.
3. If check rejects it, the writer may answer again, at most twice more (three attempts in all).
   The only extra input is the rejection lines check printed, word for word. No hints, no earlier
   answer pasted in, no saying which calls were kept. Expect unflagged calls to change: a
   re-answer redraws the whole answer (this is how the Snell call changed on 2026-10-04).
4. Publish the latest attempt only. `pilot publish` refuses a response that was never checked, one
   that is not the latest attempt, one that follows an unrejected attempt, and a fourth attempt.
   The row keeps `attempts` and `attempt_hashes`.
5. Stability samples (extra answers for diagnosis) are drawn only after the brief is published,
   are never offered to `pilot publish`, and are saved under
   `evidence/analyst_consistency/<date>_<game>/` and compared with `scripts/analyst_consistency.py`.
6. Preparing a game again freezes a new request and starts a new attempt count.

Finding (docs/research/ANALYST_CONSISTENCY.md): the prompt gives no minimum gap between the model's
estimate and the price, so the same reading can come out as a take or a pass.

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

## NFL (session-assisted, its own files)

The same flow as the MLB steps above, for football, into its own ledger (`evidence/analyst_pilot_nfl_v1.jsonl`,
never the MLB pilot's). Reference: "The NFL brief" in `docs/AI_ANALYST.md`. The publication rule is the
same: the first answer is the candidate, a re-answer only after a checker rejection and only with the
rejection lines, the latest attempt is the only one that can be published.

**Commands** (dates are the Eastern game date; clubs are the nflverse codes, the Rams are `LA`):

```
python -m src.datasvc.cli nfl update                                  # injury reports and finished scores (reads nflverse; the owner's step)
python -m src.cli analyst pilot prepare --sport nfl --date 2026-10-18 --game LAC@KC
python -m src.cli analyst pilot check   --sport nfl --dir evidence/analyst_pilot_nfl/2026-10-18_LAC-KC --response evidence/analyst_pilot_nfl/2026-10-18_LAC-KC/answer.json
python -m src.cli analyst pilot publish --sport nfl --dir evidence/analyst_pilot_nfl/2026-10-18_LAC-KC --response evidence/analyst_pilot_nfl/2026-10-18_LAC-KC/answer.json --model claude-sonnet-5-5 --tokens-in N --tokens-out N --seconds S --operator-minutes M
python -m src.cli analyst grade  --sport nfl --date 2026-10-18        # after the games, once `nfl update` has the scores
python -m src.cli analyst record --sport nfl
```

1. Before the first freeze of the day, pull the latest captured prices (fetch and merge the working
   branch) and run `python -m src.datasvc.cli nfl update` so the week's injury report is in the store.
   `prepare` reads `data/datasvc/nfl` and `data/processed/odds_multibook.jsonl` as they are on this
   computer and fetches nothing.
2. `prepare` prints the packet hash, the slot count, the missing count and the request's input token
   estimate (about 9,500 for a typical game). A rehearsal (`--scratch DIR`) can be checked and never
   published.
3. A Sonnet subagent, given only `request.json`, writes `answer.json` in the folder. `check`, answer
   again only on a rejection, then `publish`. **Publish within 90 minutes of `prepare`, and before
   kickoff**; both are enforced.
4. NFL rejections to expect: a team written next to a signed number that is not the quoted spread
   ("LAC +4" when the spread is +7.5), "Over" or "Under" next to a number that is not the quoted total, a
   player named who is not on the injury report or the quarterback listing, and a take at -200 or worse.
   Give the writer the rejection lines and nothing else.
5. Point the public sample at an NFL brief by adding `"sport": "nfl"` to `config/sample_brief.json`
   (`{"date": "2026-10-18", "away": "LAC", "home": "KC", "sport": "nfl"}`); leaving the field out means MLB.
   The paid page is `#/nfl/brief/2026-10-18/LAC/KC`; the route is `GET /analyst/nfl/2026-10-18/LAC/KC`.
6. Commit the NFL ledger, the packet folder and the config by path, as in step 8 above.

**When to freeze: about three hours before kickoff.** Prices keep moving, and the store takes the week's injury report as out 24 hours before kickoff, so a
freeze three hours out has the report and a close line while leaving time to write, check and publish
inside the 90 minutes. Sunday 2026-10-18, Pacific time (PDT, UTC-7):

| Freeze | Prepare these | Kickoff |
|---|---|---|
| Sun 03:30 (optional) | HOU@JAX (Wembley, London) | 06:30 |
| Sun 07:00 | BAL@CLE, CAR@PHI, CHI@ATL, NO@NYG, NYJ@NE, PIT@TB, TEN@IND | 10:00 |
| Sun 10:00 | ARI@LA, BUF@LV, LAC@KC; and DAL@GB if one freeze is all you want for the afternoon | 13:05, 13:25, 13:25; 17:20 |
| Sun 14:20 (optional) | DAL@GB, to get a late line instead of a seven-hour-old one | 17:20 |

The 10:00 am PT early games need the 07:00 freeze, so a single later freeze at 10:00 covers the 1:05 pm
and 1:25 pm PT games and the night game together. Seven games at 07:00 is the heavy session: `prepare`
all seven first (each packet is stamped when it is built, and the 90 minutes run from that stamp), then
have the writers answer in parallel. A game that cannot be published in time is skipped, not forced; a
game whose packet is older than 90 minutes is prepared again. Monday night (WAS@SF, dated 2026-10-19) has
its own date.

**Thin by nature.** The store holds no NFL player-prop prices and no weather forecast, so a brief is three
markets (moneyline, spread, total) and says weather is missing for an outdoor game. A weekly injury report
tells who is listed, not who matters. Early in a season a form window is three games or fewer, and the
brief should say so and pass.

## What never happens

No brief is published after first pitch. No call is edited after publishing; a correction is a
new published version. Nothing here turns billing on or sends a message to anyone.

## Desk and persona hounds

Seven model-written hounds (the Desk and six personas) bet paper units into `evidence/hounds_desk_v1.jsonl`.
The delivery is session-assisted exactly like the brief above: a Claude Code session must be open, the
parent session spawns one foreground Sonnet subagent per request file, and there is no API key. Reference:
`docs/DESK_HOUNDS.md`; rules: `docs/PREREG_DESK_HOUNDS.md` (read it once; every rule below is in it).

Caps, enforced by code: at most 2 games a run and at most 30 subagent answers a run (a game is 13 answers, so two
games leave 4 re-answers). Football works the same way with `--sport nfl`.

### Parent steps

1. Bring the stores current as in steps 1 and 2 of "Steps" above (display refresh, merge the latest captured
   prices, refresh lineups). For football run `python -m src.datasvc.cli nfl update` first.
2. Freeze at most two games, about 2.5 hours before first pitch (football: about 3 hours before kickoff).
   The packet is good for 90 minutes at publish, so do not freeze a game you cannot finish:
   `python -m src.hounds.desk prepare --date YYYY-MM-DD --game AWAY@HOME [--sport nfl]`
   It prints the packet hash, the event id and the token estimate. A third open game is refused. `--rehearsal`
   marks a folder that can be planned and checked but never published (use it for a dry run).
3. Plan: `python -m src.hounds.desk session-plan --date YYYY-MM-DD`
   It writes every request that is ready and prints the jobs: one request file and one answer file each, plus the
   exact subagent prompt. The first plan lists the four analysts and the six personas for each game (wave 1). Add `--json` to get the same jobs as one JSON object (request, answer and prompt per job) for a scheduled task.
4. Start one FOREGROUND Sonnet subagent per job (all jobs of a wave in one message, so they run together). Each is
   given only the prompt the plan printed: read that one request file, write that one answer file. No other file, no
   search, no hint about which way to lean. Do not edit an answer by hand.
5. Check: `python -m src.hounds.desk session-check --date YYYY-MM-DD`
   Every answer file is recorded as an attempt and checked; rejections are printed with the checker's lines.
6. Repeat 3 to 5. Wave 2 (bull, bear) appears when the four analysts are final, wave 3 (the desk head) when the
   bull and bear are. A rejected stage appears again as a re-answer whose request holds the rejection lines and
   nothing else.
7. When `session-plan` prints `EVERY STAGE IS FINAL`, publish within 90 minutes of step 2 and before first pitch:
   `python -m src.hounds.desk publish --date YYYY-MM-DD --model claude-sonnet-5-5 [--tokens-in N --tokens-out N --seconds S --operator-minutes M]`
   A hound whose decision stage is not final is skipped (not counted as a pass) and can be published in a later
   call before the game starts.
8. At any point: `python -m src.hounds.desk session-status --date YYYY-MM-DD` shows answered, checked and published.
9. After the games: `python -m src.hounds.desk grade --date YYYY-MM-DD` (football needs `nfl update` first), then
   `python -m src.hounds.desk verify`. Commit the ledger and the game folders by path; push in the minute 15 to 39
   window.

### The publication rule (same as the brief, per stage)

The first answer to a stage's request is the candidate. Answer again only because the checker rejected it, at most
twice (three attempts), with the rejection lines as the only extra input. An answer to a stage that is already clean
is refused. Never draw extra answers "to see". A strike by the code risk manager (a TAKE at -200 or worse, a price
that is not the best quote, a probability that does not beat the market's number, a persona's rule, a third TAKE) is
a pass and never earns a new answer.

### What never happens

Nothing here is published after first pitch, edited after publishing, or sized. Do not describe a hound's record as
anything but paper results of one model's reading. A hound that changes (prompt, schema or rule) is a new hound id.
