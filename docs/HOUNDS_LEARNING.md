# The Hounds learning loop (champion / challenger)

Paper only, not advice. The rules, with every number, are `docs/PREREG_LEARNING_LOOP.md`, committed before
any of this code existed. This file is the operator's guide: what runs where, the commands, and what is not
done. Code: `src/hounds/learning/`. Pages: `web/learning.html`, the "Versions and challengers" section of
`web/hound.html`. Routes: `api/hounds_learning.py`.

## The idea in five lines

1. Every hound has one **champion** version that races publicly. A coach (a frontier model, through the
   signed door for user hounds, through the CLI for pack hounds) may **propose a challenger** with a
   hypothesis and the evidence it read. A proposal never changes a hound.
2. The challenger runs in **shadow** on the same games at the same prices as its champion, forward only,
   through the champion's own engine, into a challenger ledger that no public page reads.
3. The **referee**, code and never a model, compares them: per game and market, `clv(challenger) -
   clv(champion)`, a pass counted as 0, looks at 100/150/200/250/300 paired slots, error spent across the
   looks, a monthly Benjamini-Hochberg batch over all of a month's challengers, caps. Only that can promote.
4. A promotion is a **new version**; the old one keeps its record (`<id>@v<n>`, retired, "superseded by version
   n+1"); a retirement goes to "tried and failed" with a one-line lesson written by code.
5. The loop measures **whether it is improving anything** (`GET /hounds/learning`) and **pauses itself** when
   it cannot show it. The owner turns it back on.

## What runs where (two scopes)

| | house scope | user scope |
|---|---|---|
| covers | the 11 pack hounds that declare `tunable` in `config/house_pack.json`, and the analyst prompt arm | every user-built hound |
| ledgers | `evidence/hounds_learning_v1.jsonl` (events), `evidence/hounds_challengers_v1.jsonl` (shadow bets), `evidence/hounds_lessons_v1.jsonl` | the same three names with `_user` inserted, beside the app database |
| proposed through | `python -m src.hounds.learning propose` (a person or the scheduled session) | the signed door `POST /hounds/{id}/coach` (needs `/coach/round` and the owner's opt-in) |
| run by | `python -m src.hounds.learning tick` | the API process: `user_runner.run_pass` calls `learning.user_scope.tick` (needs `HOUNDS_ENGINE=on`) |
| pause | rewrites `config/hounds_coach.json` to `enabled: false` with the reason | `hounds_coach_pause.json` beside the app database |

Each scope has its own caps, its own monthly BH family, its own lessons and its own pause (prereg section 14:
the facts live on two machines). The public scorecard sums the counts and shows both.

## Owner steps (nothing here was done for you)

* **The coach switch**: `config/hounds_coach.json` `{"enabled": true}`. It shipped off and the owner turned it on
  on 2026-10-18 (`docs/COACH_REPORT_CARD.md`: the practice lane that grades every coach suggestion by code while
  the pre-registered loop waits for its 50 graded bets).
* **Run the house tick in the slot.** Add one line after the `pack_run` / `pack_settle` lines of
  `scripts/capture_slot.sh` (a workflow or script edit is the owner's, so it was not made):
  `python3 -m src.hounds.learning tick --skip-scorecard 2>&1 | tail -n 6 | sed 's/^/  /' || true`. Run
  `python3 -m src.hounds.learning scorecard` once a day (a cron step or by hand); the scorecard builds the
  public stats book, which takes seconds. `evidence/` is staged wholesale by the capture scripts, so the new
  ledgers are committed with the rest.
* **Resume after an auto-pause**: `python -m src.hounds.learning resume --scope house|user --reason "..."`.
* **Monthly**: `python -m src.hounds.learning director-pack --month YYYY-MM [--run-tests]`, give the file to a
  frontier model, save its answer by hand as `docs/director/YYYY-MM.md`. Nothing reads that file back.
* **Prompt arm** (no model call unless you type it): see "The analyst prompt arm".

## Commands

```
python -m src.hounds.learning status | verify | lessons [--hound ID]
python -m src.hounds.learning coach-scorecard --hound professor_paws        # JSON for the coach
python -m src.hounds.learning propose --hound professor_paws --params '{"GAP": 0.03}' \
       --hypothesis "why this should beat the champion" --evidence record.bets,clv
python -m src.hounds.learning shadow | settle | referee | scorecard | tick
python -m src.hounds.learning resume --reason "..." [--scope user]
python -m src.hounds.learning director-pack --month 2026-11 [--run-tests] [--out PATH]
```

Testing seams on every command: `--root`, `--user-dir`, `--champion-ledger`, `--coach-config`, `--now`.

## What a pack hound can change

Only knobs declared in `config/house_pack.json` under `tunable`: name (a module-level constant), default (must
equal the live value; a test holds the two together), `min`, `max`, `step`, and `renders`, the exact strings
of the hound's `rule_text` that state it. A challenger is a set of values (at most 2 differ from the
champion's, on the step grid); its published rule text is **generated** by substitution, so the words always
say what the code does. Hounds with a declaration today: professor_paws, totals_terrier, relief_retriever,
gridiron_greyhound, steamy_setter, stale_bread_beagle, bargain_bloodhound, hot_streak_husky, grudge_bulldog,
jetlag_jack, pack_leader. Controls, for-fun hounds, engine-backed hounds, the AI desk and the Old Dog have none.

A knob is applied by patching the module constant for the length of that hound's own `pick` call only
(`tunables.VersionedHound`, under a lock, restored in a `finally`), so an ensemble's voters are never changed
by a challenger of one of them. A promoted champion version is run the same way by `pack_run` (it asks
`champions.champion_versions`), and every bet it writes carries `hound_version` and its `params`.

## What the referee is allowed to read

Closing-line value per bet from the public stats machinery (`boards.scan` + `stats.attach_clv`, the same
numbers as the race). A slot is excluded, never zero, when a bet has no measurable close; a champion-only
slot counts as a challenger pass only if the shadow runner's `shadow_coverage` event says it looked at that
game (a down runner cannot hand a challenger free wins); and the sample stops at the first slot not yet
settled, so "the first 100" never changes after the fact. A challenger that wins by abstaining is stopped by
the volume floor (at least 50 measurable bets and half the champion's).

## What is not done, on purpose or for lack of a place to put it

* **The coach is not built.** The doors, the guards, the payloads and the referee are; no model is called by
  any of it. Who calls the door (Zapier or the scheduled session) is the owner's wiring.
* **One BH family per scope**, not one across the two machines (prereg section 14).
* **No challengers for** engine-backed hounds (signals, baselines), the AI desk hounds, the Old Dog, and
  pack hounds whose price band is a class constant (`chalk_chihuahua`, `home_dog_hank`,
  `scrappy_schnauzer`) or that are controls or for fun. The analyst arm covers MLB only (the NFL and UFC
  analysts have their own prompts and ledgers).
* **Detection power is low by design**: with a paired difference SD of 3 points per slot, 100 slots cannot
  detect a true improvement under about 1 point (prereg section 6). A quiet page is the loop working.
* **Promotion changes the public stats only after the next pack run** writes a bet under the new version.
* `evidence/hounds_challengers_v1.jsonl` and the learning ledgers are new evidence stores; they are appended
  by the CLI and verified by `learning verify` (and the scorecard's `chain` field).

## The analyst prompt arm

`src/analyst/prompt_arm.py`. The shipped MLB brief prompt is the champion. A challenger is a whole alternative
prompt text, stored content-addressed in `evidence/analyst_prompts/`. `shadow --date D` answers the champion's
FROZEN packets of D under the challenger prompt, through `analyst.analyze` (spend cap, schema, retries),
`critic.verify` and `ledger.publish` (which refuses a game that has started), into
`evidence/analyst_prompt_challengers/<id>/`. Without `--confirm-spend` it is a dry run; without an API key it
is blocked. `grade --date D` grades the stored answers with the champion's own grader. `referee` pairs games
(value = paper units of the TAKE calls, a pass 0), looks at 150/225/300/375/450 games with the same spending
table and the same monthly BH family, one live challenger at a time. A promotion changes which prompt text
`situation_arm.mlb_arm("A")` returns, labelled `analyst_prompt_v5+<challenger id>`; the champion's published
rows are never touched. A promoted prompt whose file is missing or altered **raises** instead of falling back.

## Failure modes this was built against

* Rewriting toward last week's results (the reference project, 29 rewrites in 11 days, zero rollbacks): a
  challenger needs 100+ paired slots, a boundary with spent error, a monthly false-discovery control, a cap of
  three promotions a month, a 30-day cooldown per hound, and an undo.
* "Improving" that cannot be told from drift: the scorecard compares the champions with two random control
  hounds over the same games, and the loop pauses itself after 60 days of trailing them.
* A model talking its way into a promotion: no field, argument or code path from a proposal reaches
  `K_DECISION` / `K_PROMOTION` (a test greps for it), and hypothesis text is stored and quoted, never read.
* A silent shadow runner flattering a challenger: coverage events, and uncovered slots are excluded.
* A broken registry stopping capture: `pack_run` runs the plain pack and says so; `verify` reports the chain.
