# Soccer history with open and closing odds (football-data.co.uk)

Code: `src/datasvc/soccer/`. Store: `data/datasvc/footballdata/` (**git-ignored, not in the web image**). Status: parser, store,
join and CLI built and tested; **the automated fetch is gated and has not been run in bulk, for the reason below.**

## Terms (checked 2026-10-20) and what we do about them

`https://www.football-data.co.uk/data.php` says the data is free but "its use is intended for private individuals only,
NOT commercial or data training products using automated bots/scrapers/AI". LineHound is a commercial product, this
module is an automated client, and the data would feed models. So:

* `soccer fetch` refuses unless the operator passes `--i-have-permission` (`fetch_season`/`fetch_range` raise
  `TermsNotAccepted` otherwise, and make no request: tested). The honest route is the site's written permission
  (its contact form), after which the fetch path is ready.
* `soccer import --csv FILE` loads a season file a person downloaded themselves; nothing is requested.
* The store is git-ignored (the repository is public; the site's data may not be redistributed) and excluded from the image.
* Exactly one file was fetched from the site, to read the real column layout and to measure the join: `E0.csv` for
  2025/26 (380 matches, 203 KB), plus the data page, notes and disclaimer page. It was not committed.
* Free alternatives, no terms problem: ESPN's own results (already stored), `espn_odds` on each ESPN game, and our own
  forward odds capture (The Odds API, already scheduled). A historical open/close archive for soccer has no other free source.

## Rows

`matches_<season>.jsonl` (season = start year, 2025 = 2025/26), key (league, match_id), versioned like every store here:

| field | meaning |
|---|---|
| `league`, `season`, `div`, `match_id` | `epl`/`laliga`/`seriea`/`bundesliga`/`ligue1` (E0, SP1, I1, D1, F1); id `E0-2025-08-15-liverpool-bournemouth` (`-2` for a repeat) |
| `date`, `time_uk`, `kickoff_utc_est` | local date and UK kickoff as the file gives them; the UTC estimate assumes UK time (BST/GMT handled), a tie-breaker only |
| `ft_home/away`, `ht_home/away`, `ft_result`, `ht_result`, `referee`, `stats` | result, half time, shots, shots on target, corners, fouls, cards |
| `odds` | `{market: {book: {"open": [...], "close": [...]}}}`, markets `1x2` (H, D, A), `ou25` (over, under), `ah` (home, away) plus `line_open`/`line_close`; books B365, PS (Pinnacle), WH, BFE (Betfair Exchange), Max, Avg |

"open" is the site's first collection (a few days before the match), "close" the closing odds (files since 2019/20; older
seasons have only the first set). Blank cells are absent, never zero. Pinnacle's feed has been stale since 2025-07-23 (the
site says so) and is often blank. A row is ~1.3 KB, so ~55 league-seasons (EPL + 4 leagues, 2015 on) would be ~25 MB
local, ~4 MB gzipped.

`joins_<season>.jsonl`: league, match_id, game_id (ESPN), method, score, day_gap, both sides' names.

## The join to ESPN game ids (`match.py`)

Candidates are ESPN games within one day of the football-data date (UTC vs local). Each side scores by token overlap with
any of the club's ESPN names (display, short, location, abbreviation; a token equals or is a 3+ letter prefix of one:
"Man City" fits "Manchester City", "Ein Frankfurt" fits "Eintracht Frankfurt"). Accepted: both sides >= 0.75 (`names`),
or one side >= 0.9 with no rival for it (`one_side`); names confirmed that way are remembered and applied to leftovers
within three days (`alias`); a seed table covers spellings no rule reaches. Pairs are taken best-first so an ESPN game is
never given to two matches, and a join whose final scores disagree with ESPN's is dropped and reported. Clubs missing from
the ESPN teams endpoint (relegated sides) are named from their games.

**Match rate, measured: EPL 2025/26, 380 of 380 football-data matches joined (100%), all by `names`, 380 scores checked,
0 disagreements, 0 ESPN games left over.** (ESPN side: `scoreboard?dates=2025` and `?dates=2026`, 2 requests.) Only the
EPL file was available for a real check, so the other four leagues are unmeasured: their seed spellings are from the
site's documented conventions, and the score cross-check will show any mismatch on the first run.

```
python -m src.datasvc.cli soccer import --league epl --season 2025 --csv E0.csv
python -m src.datasvc.cli soccer match  --league epl
python -m src.datasvc.cli soccer odds   --league epl --game-id 401878769
python -m src.datasvc.cli soccer fetch  --league epl --from 2015 --to 2025 --i-have-permission   # only with the site's permission
```
