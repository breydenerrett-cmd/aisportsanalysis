# Decision: the UFC favourites card is paused after 2026-10-03

For Brey. Owner decision of 2026-10-03, wired the same day. One config value
turns it back on.

## The decision

The public UFC rule, UFC_CARD_V1, takes the market favourite in each bout. The
owner's words:

> "UFC is one of the most volatile examples... Do you understand that there needs to be actual analysis"

New public UFC favourites picks stop after **2026-10-03**. The pause lasts until
a real fight analysis product replaces the rule (a UFC data layer and an AI
analyst are being built separately; nothing here depends on them).

**Effective:** the last public date is `2026-10-03`. Tonight's card (2026-10-03)
keeps publishing exactly as it does now: its bouts lock 90 minutes before each
bout, and later slots that day still write their locked versions. Every date
after it is paused.

## What stops

| Where | Before | Now, for a date after the last public date |
|---|---|---|
| `scripts/capture_slot.sh` | every slot ran `card publish --sport mma` | prints `== ufc card publish: paused after 2026-10-03 (config/ufc_public_card.json) ==` and moves on |
| `GET /card/{date}?sport=mma` (and `GET /card?sport=mma`) | a date with no published row was built live from the odds store and served as provisional favourites picks | answers `paused: true`, no picks, and the reason below. Nothing is built, read from the ledger, or cached |
| The UFC Gameday page (`#/ufc`) | showed the card, or last night's card when today had none | shows the reason as its empty state, with links to the UFC record and to tonight's MLB picks |

The reason a reader sees, verbatim from the API:

> UFC picks are paused. The old rule took the betting favourite in every fight, which is not analysis. Picks come back when each fight has a real breakdown behind it. Every UFC pick made so far stays on the record page.

## What stays

- **Every published pick, row and record.** No ledger row was edited, deleted or
  re-signed. `evidence/cards_mma_v1.jsonl` is untouched.
- **The record.** `GET /card/record?sport=mma`, `GET /card/history?sport=mma`, the
  UFC record page (`#/ufc/record`) and the UFC example accounts do not read the
  pause and answer as before. Tonight's picks appear there once graded.
- **Grading.** `card settle --sport mma` and the manual result entry are not
  gated, so the published picks still settle.
- **Odds capture.** `python3 -m src.cli ufc capture` still runs every slot.
- **Dates on or before the last public date.** Served exactly as before, frozen
  rows byte for byte.
- **The rule file.** `src/analysis/ufc_card.py` was not edited, and neither was
  any other file the fingerprint tests cover (`card_ledger.py`, `card_v2.py`,
  `best_bets_card.py`).

## How to reverse it

One value: `favourites_rule_last_public_date` in `config/ufc_public_card.json`.
Set it to the last date the rule should publish for (a date far ahead turns
everything back on), commit, and let it deploy.

- The capture runner reads the file from its checkout, so the next slot follows
  it.
- The API reads the file from the deployed image. The image did not copy
  `config/` on 2026-10-03, so until it does the API cannot see the file and uses
  the built-in date, `DEFAULT_LAST_PUBLIC_DATE` in
  `src/appstate/ufc_public_card.py` (also 2026-10-03). In that state the pause
  holds, and a later date in the config will not reach the API until the image
  carries it or that constant is changed as well.

A missing, unreadable or malformed config never turns the favourites back on.
It falls back to the built-in 2026-10-03, so dates on or before it are served and
published as before and later ones stay paused, and one warning is logged
naming the problem. The script has the same floor in shell if even the helper
cannot run.

## What a reader sees, and when

The card's date is the UTC date of each bout's start; the capture slot's date is
the Eastern date; the UFC page asks the API for "today" with no date, which is
the server's own date (UTC on Fly, where no timezone is set). So at 00:00 UTC on
2026-10-04 (8pm Eastern on the 3rd) the page's "today" is the 4th and reads as
paused. Tonight's picks leave the Gameday page then and show on the record page
once they are graded (UFC results are entered by hand). A date typed into the
API is paused or served by the same comparison on its own date.

## Where it lives

- `config/ufc_public_card.json`: the one place that decides it.
- `src/appstate/ufc_public_card.py`: reads it (anchored at the repository root),
  holds the reason sentence and the built-in fallback; `python3 -m
  src.appstate.ufc_public_card` prints the date for the script.
- `scripts/capture_slot.sh`, `api/card.py`, `web/js/card.js`: act on it.
- Tests: `tests/test_ufc_public_card.py`, `tests/test_capture_slot_ufc_pause.py`,
  `tests/test_api_card_ufc_paused.py`, `tests/test_web_ufc_paused_page.py`.

## Not changed here

Public copy that still describes UFC picks as live: the landing page (hero line
"Tonight's MLB, NFL and UFC bets", the FAQ line that says MLB, NFL and UFC all
carry live picks, the UFC tile's "Picks published on event nights.") and the
page description meta tags. That copy is the owner's call, so it was left alone.
