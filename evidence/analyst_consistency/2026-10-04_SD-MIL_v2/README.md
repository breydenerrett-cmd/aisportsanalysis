# Padres at Brewers 2026-10-04, version 2: consistency samples

Request: `evidence/analyst_pilot/2026-10-04_SD-MIL/request.json` (prompt v3, frozen 2026-10-04).

- `published_answer_copy.json`: a copy of the answer published as version 2 at 16:54Z. The
  original and the ledger are unchanged.
- `sample_a_unpublished_answer.json`, `sample_b_unpublished_answer.json`: two more answers to the
  same request, written on 2026-10-05 after the game, by the same model, each in a fresh session
  that read only the request. Never published, never offered to `pilot publish`.

Result (`table.md`): the published answer TOOK the Brewers moneyline at -128 with an estimate of
0.58. Both samples PASSED on it with an estimate of 0.55. The run line and total agree in all
three. The published call is one model reading and was not reproduced.

These are diagnostic samples, not sporting evidence. The samples were drawn after the game ended;
the request contains nothing from the game, and the writers were given nothing else.
