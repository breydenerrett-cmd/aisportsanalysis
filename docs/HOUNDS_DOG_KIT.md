# The dog kit (2026-10-19)

Owner ask: let a user's dog choose a bet in the moment, fire it by hand, be asked why it did what it did, be rated
and dressed, and make the Training camp the place where dogs get better. Everything is computed from data; no
model is called and no network is touched (a test reads the package source to prove it).

Code: `src/hounds/interact/` (no FastAPI import anywhere), routes in `api/hounds_interact.py`, web in
`web/js/dog-*.js`, `web/css/dog-kit.css`, `web/hound.html` (two containers) and `web/learning.html`.

| Feature | Route | Notes |
|---|---|---|
| Unleash (the button and the tab; the route keeps the old word) | `POST /hounds/{id}/fire` | Read only. User dogs: `user_engine.evaluate` on the newest stored capture of each market. House dogs: `pack_run.choose` over a board built now, champion knob values. A pick says its board age, its usual placing time and the checks it passed; "nothing qualifies" lists the closest misses with the gap. A preview is not a ticket. |
| Take them out back (the burial) | `POST /hounds/{id}/out-back` `{"confirm": true}`, `GET /hounds/{id}/headstone`, `GET /hounds/graveyard` | Owner of a MEMBER dog only (a house dog is 422 `not_a_member_dog`; someone else's dog is 404). Refused while the dog has an open or ungraded ticket (409 `open_tickets`, read from the ledger, not the cached book) and for a dog already buried (409 `already_buried`). Status becomes `buried` (the engine only runs `running` dogs), one append-only `hound_events` row freezes the headstone (final W-L-P, paper bankroll, best win, dates, look, deterministic epitaph), and the dog's plan slot is free again (free 1 / paid 5). Logic: `src/hounds/interact/outback.py`; the page asks twice (`web/js/dog-rites.js`). |
| Send to training | `POST /hounds/{id}/train` `{"confirm": true}` | Owner of a MEMBER dog only; same open-ticket refusal. Once a lineage has trained, the version it is on needs 5 NEW settled bets before it can train again (409 `training_too_soon`); a first training under 5 settled bets is a labelled light adjustment. The dog's settled bets are cut by sport, market, price band, side, favourite/underdog and rule; 1 to 3 deterministic changes that only NARROW the dog (validated by `user_spec.validate_spec`, so the -200 cap holds) become the next version via `user_store.create_version` with `coached_from` set, a fresh record and a `trained` event row. The card never says the new version is better. Logic: `src/hounds/interact/training.py`. An optional AI brief goes to the owner's Zapier hook (`ZAPIER_TRANSLATE_HOOK_URL`) from a background thread; the shown paragraph is always written by code and nothing waits on the hook. |
| Manual pick | `POST /hounds/{id}/manual`, `GET` | Owner only, running builder dog, a pick the rule would make now, game not started, board under 75 minutes old, one per game and market, 5 a day, -200 guard. Own ledger `hounds_manual_v1.jsonl` beside the user ledger; nothing in stats, the leaderboard, the referee or the learning loop reads it. Graded by `user_settle.settle` pointed at that file (lazily on read, and in the engine pass). |
| Ask | `GET/POST /hounds/{id}/ask` | `ask.classify` (word and phrase rules) then one builder per intent. Rule text through the spec-to-English renderer when `src/hounds/english` exists, else `rule_text`. |
| Feedback | `GET/POST /hounds/{id}/feedback`, `POST /hounds/{id}/suggest` | Table `hound_feedback`: one vote per (user, dog, target); notes pass the name blocklist; the public sees counts, only the owner sees notes and suggestions. Feedback never changes a dog. |
| Locker room | `GET/PUT /hounds/{id}/look`, `GET /hounds/looks?ids=` | Table `hound_looks`, keyed by lineage root so versions keep the look. Whitelisted keys only (`look.py`); `web/js/dog-avatar.js` holds the same lists (tested). |
| Backtest (the route and code say drill) | `POST /hounds/drill` | `{dog_id | spec, days: 7|14|30}` or `{dog_id, season: "s2"}`. Replays the rule in a temporary ledger (user engine replay + `user_settle`, or `pack_run` replay + `pack_settle` as in `coach_grade.grade_hindsight`). Labelled "Backtest (hindsight, not counted in the record)", `counted: false`, with the picks also in paper dollars (`bankroll`, `usd`). A month takes about 20 seconds locally. |
| Camp | `GET /hounds/camp/mine`, `GET /hounds/{id}/kit` | The camp's "Your dogs in training" and what a visitor may do on a dog's page. |

Wiring the badge elsewhere: put `data-dog-avatar="<hound id>" data-dog-size="36"` on a monogram and call
`hydrateAvatars(root)` from `dog-avatar.js` after rendering; it swaps in the badge for builder dogs that have a look.

The owner's button wording "Lock it in" is "Record as a manual pick" on the pages: the site-wide voice test bans the
word "lock" on public pages.
