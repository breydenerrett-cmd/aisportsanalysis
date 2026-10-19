# The dog kit (2026-10-19)

Owner ask: let a user's dog choose a bet in the moment, fire it by hand, be asked why it did what it did, be rated
and dressed, and make the Training camp the place where dogs get better. Everything is computed from data; no
model is called and no network is touched (a test reads the package source to prove it).

Code: `src/hounds/interact/` (no FastAPI import anywhere), routes in `api/hounds_interact.py`, web in
`web/js/dog-*.js`, `web/css/dog-kit.css`, `web/hound.html` (two containers) and `web/learning.html`.

| Feature | Route | Notes |
|---|---|---|
| Fire now | `POST /hounds/{id}/fire` | Read only. User dogs: `user_engine.evaluate` on the newest stored capture of each market. House dogs: `pack_run.choose` over a board built now, champion knob values. A pick says its board age, its usual placing time and the checks it passed; "nothing qualifies" lists the closest misses with the gap. A preview is not a ticket. |
| Manual pick | `POST /hounds/{id}/manual`, `GET` | Owner only, running builder dog, a pick the rule would make now, game not started, board under 75 minutes old, one per game and market, 5 a day, -200 guard. Own ledger `hounds_manual_v1.jsonl` beside the user ledger; nothing in stats, the leaderboard, the referee or the learning loop reads it. Graded by `user_settle.settle` pointed at that file (lazily on read, and in the engine pass). |
| Ask | `GET/POST /hounds/{id}/ask` | `ask.classify` (word and phrase rules) then one builder per intent. Rule text through the spec-to-English renderer when `src/hounds/english` exists, else `rule_text`. |
| Feedback | `GET/POST /hounds/{id}/feedback`, `POST /hounds/{id}/suggest` | Table `hound_feedback`: one vote per (user, dog, target); notes pass the name blocklist; the public sees counts, only the owner sees notes and suggestions. Feedback never changes a dog. |
| Locker room | `GET/PUT /hounds/{id}/look`, `GET /hounds/looks?ids=` | Table `hound_looks`, keyed by lineage root so versions keep the look. Whitelisted keys only (`look.py`); `web/js/dog-avatar.js` holds the same lists (tested). |
| Drill | `POST /hounds/drill` | `{dog_id | spec, days: 7|14|30}`. Replays the rule in a temporary ledger (user engine replay + `user_settle`, or `pack_run` replay + `pack_settle` as in `coach_grade.grade_hindsight`). Labelled "Hindsight drill: not counted", `counted: false`. A month takes about 20 seconds locally. |
| Camp | `GET /hounds/camp/mine`, `GET /hounds/{id}/kit` | The camp's "Your dogs in training" and what a visitor may do on a dog's page. |

Wiring the badge elsewhere: put `data-dog-avatar="<hound id>" data-dog-size="36"` on a monogram and call
`hydrateAvatars(root)` from `dog-avatar.js` after rendering; it swaps in the badge for builder dogs that have a look.

The owner's button wording "Lock it in" is "Record as a manual pick" on the pages: the site-wide voice test bans the
word "lock" on public pages.
