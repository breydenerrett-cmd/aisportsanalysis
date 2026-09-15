# Site redesign and full-page audit, 2026-09-15

## The owner's request (verbatim)

> "can we punish and rewire eveeyrhunf ai its lice and add exiting news
> banners and redesigns and make it how like TENIIS (coming soon) in top ight
> red rex and NFL coming soon as well, make sure every singkenpage vets audited
> so it all feels unison and like one complete system and usw rijtnwrface and
> exoectatijs"

Read as: publish and rewire everything so it is live; add exciting news
banners and the redesigns; show "TENNIS (coming soon)" and "NFL (coming soon)"
in red text at the top right; audit every single page so the whole site feels
unified, one complete system, in its user interface and in the expectations it
sets.

## Decisions (orchestrator; each is the stated default, owner can overrule)

1. **"Live" means the hosted site people use: `linehound-staging.fly.dev`.**
   It deploys automatically on every push to the working branch. The owner's
   request is the explicit approval the design review's build rules asked for
   before a staging deploy. **Production (`linehound-prod`) is not deployed
   by this work**: it has no deploy workflow and the forwarded review said
   production is not authorised. If the owner wants production, that is a
   separate go-ahead.
2. **"Redesigns" is approval of Direction A's look across the whole app**
   (`Desktop/LineHound_Review_2026-09-14/concepts/A_franchise_desk/`), under
   the amendment's rules (`05_AMENDMENT_2026-09-14.md` sections 1, 7, 8):
   - A covers the menu structure, visual treatment and responsive layout, not
     the old three-number card panels, which are superseded.
   - Compact pick card: rank and matchup, exact selection with market and
     line, odds and book, publication time, one sentence of reasoning, and a
     material limitation only when one exists. The market / our number /
     break-even comparison moves into "View breakdown", one tap away.
   - Every visible status comes from a recorded field; nothing is invented.
   - One experimental notice above the picks, not a badge on everything.
   - No Watchlist section. Record wording describes today's policy exactly.
   - Selection, ranking, locking, settlement, the ledgers, billing, access
     control and the capture jobs do not change.
3. **News banner.** One announcement strip under the top bar on every page,
   landing included, dismissible and remembered per browser. Every item must
   be true today:
   - COMING SOON · NFL: picks for this season are being tested on this week's
     games before they go on the record.
   - COMING SOON · Tennis: a match board for ATP and WTA events.
   - NEW · Player props now sit on the daily card with the game picks.
   - NEW · Game times show in your own time zone.
4. **Top right, in red: "NFL · COMING SOON" and "TENNIS · COMING SOON".**
   They replace the MLB / NFL / Tennis / Live switcher added yesterday. Each
   opens a coming-soon page for that sport (`#/nfl`, `#/tennis`). The earlier
   NFL and tennis routes (`#/nfl/today`, `#/nfl/record`, `#/tennis/board`) show
   the same coming-soon page. The NFL and tennis pipelines keep capturing and
   forward-testing privately; nothing on those pages claims picks exist.
5. **Live leaves the public chrome.** `#/live` stays reachable by URL for
   internal testing, and the landing page may say Live is planned, not
   available.
6. **Every sport is its own section with its own sub menu** (owner, later the
   same day: "Every category needs its own sub menu so people can pay for each
   and every sport individually"). The top level is the sport: MLB now; NFL and
   TENNIS marked coming soon in red; NBA and NHL can be added to the registry
   later. Inside a sport, its sub menu. Each sport shows its own price and
   subscribe action once per-sport billing lands
   (`docs/PER_SPORT_PRICING_PLAN.md`, in progress); until then the layout
   leaves room for it and nothing on the page implies a per-sport plan can be
   bought yet.
7. **MLB's sub menu.** GAMEDAY · MATCHUPS · PROPS · RESULTS (plus BETS for
   signed-in users, hidden in the public demo as today). The amendment named
   Gameday / Matchups / Results; PROPS stays because the owner asked for it by
   name on 2026-09-12 and props are now on the card. CHECK leaves the main
   navigation and the fixed "Check a bet" bar goes; Bet Check's route and
   function stay, reachable from matchup pages and the footer.
8. **One system.** Every page uses the same shell, page header pattern
   (eyebrow, title, one-line purpose, status line), section heads, buttons,
   cards, tables, empty, loading and error states, and the same voice. Every
   page is captured at 1440x900, 390x844 and 360x780 before and after.
9. **Language.** Plain English; no page promises an outcome, names a model's
   number as a probability of winning, or claims an edge. The customer
   language tests stay green.

## Process

1. Capture every page as deployed (done 2026-09-15, desktop and phone).
2. Audit each page against Direction A, the amendment rules and the rest of
   the site; write findings.
3. Write the unified design spec from the findings (`docs/DESIGN_SYSTEM.md`).
4. Build in disjoint file groups: shell and shared components first, then the
   pages in parallel.
5. Re-capture every page locally at three widths; check each against the spec;
   fix; run the full test suite; push (staging deploys); capture staging.
