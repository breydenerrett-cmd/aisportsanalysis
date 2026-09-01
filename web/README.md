# web/ — structural reference client

**Purpose.** Prove the API (`docs/API_CONTRACTS.md`) is consumable
end-to-end with semantic HTML and minimal vanilla JS, and give the
approved design system a ready structure to attach to. This client makes
**zero aesthetic decisions** — no colors, no fonts, no layout CSS beyond
the single `[hidden]{display:none}` rule in `index.html`'s `<head>`. If
something here looks plain, that is the point, not an oversight.

## What's here

```
web/
  index.html        app shell: nav landmark, token-entry form, <main> outlet, disclaimer footer
  js/
    api.js          fetch wrapper: attaches Authorization: Bearer <token> from localStorage
    dom.js          element-builder + generic JSON-to-<dl>/<ul> renderer for opaque fields
    meta.js         GET /meta disclaimer footer + shared staleness renderer
    today.js        TODAY view       -- GET /today, GET /changed/{date}
    games.js        GAMES view       -- GET /games/{date}, GET /game/{date}/{away}/{home}
    betcheck.js     BET CHECK view   -- POST /betcheck (the fixed skeleton, see below)
    odds.js         ODDS view        -- GET /odds/{date}, GET /odds/{date}/{away}/{home}
    mybets.js       MY BETS view     -- GET/POST/DELETE /my-bets
    main.js         hash router + nav + token form wiring
  README.md         this file
```

Served by `api/web.py` (a router, not wired into `api/app.py` — see that
file's module docstring for the one line its owner adds) or by any static
file server pointed at this directory; see "Running it" below.

## How the design system attaches later

1. **Every element a design needs to style carries a `class` or
   `data-*` attribute already** — this client was built hook-first. A
   design pass adds a stylesheet (and, if truly needed, presentational
   markup changes) that targets these hooks; it does not need to touch
   the view modules' data-fetching or rendering logic to reskin the page.
2. **Class naming contract — BEM-ish, content not appearance:**
   `block`, `block__element`, with the value describing *what the thing
   is* (`bet-check-support`, `slate-entry__verdict`, `staleness__key`),
   never *how it should look* (no `bet-check-red`, `text-large`,
   `card-shadow`). `tests/test_web_structure.py` enforces this — a class
   name containing a color or font/typography word fails the suite.
3. **`data-hook="..."` attributes are the stable attachment points for
   both a design system and any future test.** They are named for
   content/purpose (`data-hook="bet-check-your-bet"`,
   `data-hook="disclaimer"`, `data-hook="staleness"`), not for a visual
   role. `data-view="..."` on each top-level `<section>` names which view
   rendered it, for a design system (or a test) that needs to select
   "the whole Bet Check view" without caring about internal structure.
4. **What must not change when a design system attaches:**
   - The **Bet Check skeleton order** — YOUR BET → SUPPORT →
     COUNTERARGUMENT → PRICES → BOTTOM LINE — is a trust mechanism
     (docs/PRODUCT_DESIGN_HANDOFF.md: "a fixed skeleton ... an omission
     becomes visible"). `betcheck.js`'s module docstring names the exact
     `data-hook` sequence; `tests/test_web_structure.py` pins it.
     Restyle freely; do not reorder the sections or make one collapse
     while the others stay open by default.
   - **Counterargument keeps equal markup weight with Support** — same
     element shape, not a de-emphasized variant. A design system may
     style them differently, but the counterargument list must never be
     rendered smaller, hidden-by-default, or visually subordinate in a
     way that makes it easy to miss (the handoff calls this out
     explicitly: "a page that only ever shows [support] is a tout").
   - **The disclaimer and staleness hooks stay rendered on every page.**
     `data-hook="disclaimer"` (app shell footer, `meta.js`) and
     `data-hook="staleness"` (per-view, wherever the API returns a
     `{observed_utc, age_seconds, has_market|has_board}`-shaped object)
     must keep rendering whatever the API returns, verbatim. A design
     pass may restyle them but must not remove them, collapse them by
     default, or replace API text with its own copy.
   - **No client-composed claims.** Every view renders strings the API
     sent (`summary`, `bottom_line`, `counterargument_lines`,
     `disclaimer`, ...) verbatim. A design system must keep doing this —
     it can restyle a sentence, not rewrite or supplement it. This is
     also why unpinned/opaque fields (`dossier`, `sections`, `gaps`, the
     odds market board) render through `dom.js`'s generic
     `renderUnknown` instead of a hand-built template: a template implies
     an assumed shape docs/API_CONTRACTS.md does not yet guarantee.
   - **`recommendation` renders whatever the API sends (always `null`
     today) and must never be turned into a displayed pick.** Ranker
     Engine 2 stays gated; this client has no code path that could
     surface a bet recommendation even if the field stopped being
     `null`, and a design pass must not add one.

## Running it

**Preferred — the FastAPI router (`api/web.py`):**

```
from api.web import router as web_router
app.include_router(web_router)
```

(This line is not present in `api/app.py` — see BOUNDARIES in this
task's brief; another lane owns that file.) Once mounted, the app is at
`/web/` on whatever host serves `api/app.py`, and every `fetch()` call in
`web/js/*.js` (relative paths like `/today`, `/betcheck`) reaches the
same origin's API with no CORS configuration needed.

**Fallback — a bare static server**, useful for opening this client
against an API running elsewhere:

```
python3 -m http.server 8080 --directory web
```

This works standalone, but every `fetch()` call is then cross-origin
against the API host, so the API needs permissive CORS (`Access-Control-
Allow-Origin`) for this client's origin, and the API's own CORS policy is
outside this file's scope. Prefer the router when you control both.

## Getting a token

There is no login flow in this client — the API's only issuance path is
the admin-gated `POST /admin/invites` (`api/auth.py`, requires
`APP_ADMIN_TOKEN`). Get a raw invite token that way, paste it into the
"Invite token" field in the header, and click "Save token"; it is kept in
this browser's `localStorage` (`aisportsanalysis.invite_token`,
`web/js/api.js`) and attached as `Authorization: Bearer <token>` to every
subsequent API call from this page.
