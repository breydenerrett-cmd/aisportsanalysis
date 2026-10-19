# LINEHOUND design benchmark, 2026-10-19

Owner ask: "Is this going to blow my socks away? Super engaging, super fun, super customizable and editable. Top-notch, like a
billion-dollar design team designed this page and the entire hub." Presentation only: no data, API meaning, rule or record
changed. Method: the design-benchmark-loop (pick real references, capture them and our pages side by side, name concrete gaps,
rebuild, re-capture, score honestly, iterate below 8).

Screenshots: `docs/design/before/` (this audit), `docs/design/after/` (the rebuild). Named `<page>-1440.png` and `<page>-390.png`.
Reference captures sit in `before/ref-*.png` (public home pages captured 2026-10-19 with the same headless browser).
Page data is the real public API (linehound.app GET /hounds, /hounds/series, /hounds/kennels), served through a local read-only
proxy so the work is checked against what a visitor sees. The signed-in kennel and studio shots use a local mock owner whose
four dogs are the public house dogs' real records, with sample looks. They show layout, not a real member.

## The three references and why

| Axis | Reference | What we take from it |
|---|---|---|
| Product clarity and density | Linear (linear.app) | One display weight at a large size, one grey for everything secondary, a product screenshot as the hero instead of illustration, hairline structure, almost no colour. |
| Character and game feel | Duolingo (duolingo.com) | A character that is the brand, drawn with a consistent rig and flat vector craft, giant tactile buttons with a pressed state, joy at the moment of success, plain-language copy. |
| Marketing polish | Stripe (stripe.com) | Hero type that does the work (large, tight, two-tone: ink then grey), a clear dual CTA, restrained one-hue gradients, cards with real product UI inside, generous and consistent section rhythm. |

## What the references do better, concretely

**Type scale.** Linear's hero is ~64px/1.0 with -0.03em tracking and a 16-18px grey subline: the jump from display to body is
~4x, and nothing lives in between. Stripe: ~44px/1.15 headline, the first clause ink and the rest grey (hierarchy inside one
sentence). Duolingo: ~28px bold rounded headline, one weight. LINEHOUND before: hero ~44px/1.1, section titles 17px, then a
dozen 11-14px variants (uppercase mono labels, mono eyebrows, 13px and 12.5px greys) so everything is "small and medium" and
nothing is big. Landing mixes three faces (Barlow Condensed, Instrument Sans, JetBrains Mono) and loads two over a CDN.

**Spacing rhythm.** Linear and Stripe use a visible 8px grid: 24/48/96 between blocks, the same gutters on every section.
LINEHOUND before: 14/18/22/26/28/32/44/56 pixel margins chosen page by page; the landing sections change width and
alignment (centred hero, left-aligned sections, 1080 and 1180 wrappers).

**Colour restraint.** Linear: near-black, two greys, one tint of the product accent, nothing else. Duolingo: one green owns every
CTA; the other colours are character art. LINEHOUND before: the hounds pages use one green (good), but the landing uses red and
orange CTAs and a cyan-teal gradient panel, the member app uses cyan links and uppercase teal tabs, and the admin uses a red
button and a condensed face. Three palettes in one hub.

**Hierarchy.** Each reference has exactly one thing to look at above the fold. LINEHOUND's landing first screen is a headline, two
buttons, a disclaimer paragraph, a link, a full table and a ticket list at equal weight; then a second hero ("Our AI desk"), a
second CTA band, then a "what you get" two-column text block. The model page opens with a Fire-now card, tabs, then a KPI wall.

**Motion.** Linear: slow, low-amplitude fades and a product loop. Duolingo: the character reacts (blink, bounce, celebrate) and
buttons physically depress. Stripe: a living gradient. LINEHOUND before: a good start (rise-in rows, count-ups, a bobbing avatar,
confetti) but one avatar for every dog, no easing/duration tokens (values .15s/.2s/.25s/.28s/.32s/.5s scattered), the studio drawer
is a 36px slide with no spring and the Save button gives text feedback only.

**Delight moments.** Duolingo celebrates correctness and shows the mascot at every state change. LINEHOUND before: confetti on a new
dog or a manual pick, but the dog itself never changes expression: the avatar is one head shape in eight coats, so a kennel of
four dogs reads as the same dog four times. No character in the leaderboard, no character in the landing hero.

**Empty states.** Duolingo and Linear fill empty with the character plus one action. LINEHOUND before: the kennels index is a
single card above 600px of empty page; the empty chart on a model page is a 9px grey line of text; the training camp is text-only.

## Page by page: before captures and gaps

Scores are 1-10 against the reference that fits the page, written before the rebuild and kept for the comparison. 8 is "could
sit next to the reference without embarrassment".

| Page | Before shots | Reference | Before | Biggest gaps |
|---|---|---|---|---|
| Landing | landing-1440 / -390 | Stripe + Linear | 4 | Two heroes, three palettes, three faces, no character, no live visual: the hero is a table. 10,000px on a phone. |
| Leaderboard | leaderboard-1440 / -390 | Linear | 6 | Clean hairline table but monogram initials instead of dogs, no podium or top-3 moment, 12 columns, filter pills wrap in three rows. |
| Model page | model-1440 / -390 | Linear + Duolingo | 5.5 | Header avatar is the default dog or a monogram, a card on top of a KPI wall, an empty CLV chart. No expression for a win streak. |
| Kennels index | kennels-1440 / -390 | Duolingo | 5 | One card on a blank screen, avatars are identical heads. |
| Public kennel | kennel-public-1440 / -390 | Duolingo | 5 | Same. |
| My kennel | kennel-mine-1440 / -390 | Duolingo | 6.5 | Good card structure; characters identical; stats in small mono-grey; build card flat. |
| Studio | studio-1440 / -390 | Duolingo (character creator) | 6 | Preview is a small tile in a grey box, swatches and chips work but no spring, no randomize, no selection animation, no celebrate on save. |
| Builder | builder-1440 / -390 | Linear | 6 | Orange monogram badge instead of a dog, form wall, swatch circles in a different palette from the dog colours. |
| Training camp | camp-1440 / -390 | Linear | 4 | 4,750px of unbroken paragraphs; every section the same weight. |
| Member app | member-app-1440 / -390 | Linear | 4 | Own palette (cyan links, uppercase tabs), a second type system, a sign-in wall. |
| Admin | admin-1440 / -390 | Linear | 4.5 | Condensed face and red CTA unlike the rest of the hub. |

(After scores, self-graded the same way, are in the table at the end of this file.)

## Design brief that came out of the audit

1. One display face and one text face (both already shipped locally in `css/fonts.css`), a modular scale with a real big step.
2. One hero accent (the existing green) plus semantic win/loss; the red/orange/cyan on landing, app and admin go.
3. A 4/8 spacing ladder, an elevation ladder, three radii, one focus ring, one easing/duration set as tokens.
4. A real dog character: breed silhouettes by vibe, layered accessories, five poses, one `renderDog()` used everywhere.
5. A landing hero that shows the product alive: the top dogs racing on their real bankroll lines.
6. The studio as a character creator: big live preview, springy selection, randomize, celebrate on save, rules editing inline.
7. Honesty unchanged: paper only, 21+, not advice, 1-800-GAMBLER, no profit or edge claim, no Bet Check promotion; small samples
   say so on the page, including the new hero.

---

# After: what was built, and an honest score

Screens: `docs/design/after/<page>-1440.png` and `-390.png` (same pages, same data, same capture method as `before/`). Gated screens
(the signed-in member app and the admin dashboard) are captured at their sign-in wall only; the studio and My kennel use the local
mock owner described at the top.

## Against each reference, axis by axis

| Axis | Reference does | LINEHOUND now |
|---|---|---|
| Type scale | Linear: one big display step, one grey. Stripe: ink-then-grey headline. | Barlow Condensed display (hero up to 84px, section titles 26-48px, scoreboard numbers 32-42px) over Instrument Sans text on one scale (12/13/15/17/22/30/48/84). Landing sections no longer mix three faces; no uppercase italic headings anywhere on the hounds pages or the landing. |
| Spacing rhythm | 8px grid, same gutters every section. | One 4/8 ladder in `css/lh.css` tokens (`--lh-s1..s9`); landing sections share a 1180 wrapper and 96/64px rhythm; cards 24px padding, 16px gaps. |
| Colour restraint | Linear: near-black plus one tint. Duolingo: one green owns every CTA. | One hero accent (green) on every page including landing, app and admin (the red and cyan calls to action are gone). Win/loss/pending are the only other colours and still ride on numbers and result words. |
| Hierarchy | One thing above the fold. | Landing: headline, one primary action, the live race. Model page: the dog, name and status, then the scoreboard cards, then each section as a card. Leaderboard: the leaders as three big dog cards above the table. |
| Motion | Linear: slow fades. Duolingo: the character reacts and buttons press. | One easing/duration token set (`--lh-ease`, `--lh-spring`, `--lh-t-fast/base/slow/hero`), page-load stagger, number count-ups, the race drawing itself, wins popping and losses settling, a spring on the studio drawer and on every studio choice. All of it inside `prefers-reduced-motion: no-preference`. |
| Delight | Duolingo: mascot at every state change. | A real dog rig (6 breeds by vibe, 5 poses, accessory layers, blink/breathe, tear, thought dots, sparkles and raised paws), used on the leaderboard rows, podium, model header, kennel cards, studio, builder, camp, landing race and sign-in wall. Dogs react to their own results (win streak is happy, loss streak is sad); tap a dog in the race and it cheers. |
| Empty states | Character plus one action. | Kennels list: "Start your own kennel" card and a breeds legend. Builder: the dog thinks until there is a name and a rule, then is happy. Sign-in wall: a thinking dog. Empty CLV chart: one calm line in a soft box. Race with no model: says so and draws nothing. |

## Self-score, same 1-10 scale (8 = could sit next to the reference)

| Page | Reference | Before | After | What is still short |
|---|---|---|---|---|
| Landing | Stripe + Linear | 4 | 8 | Below the fold the AI desk record and the sports tiles are still dense figure blocks (honesty content kept as is); the race has only two points per line because Season 2 is two days old. |
| Leaderboard | Linear | 6 | 8 | The table is still 12 columns (it scrolls inside its own wrapper on a phone). |
| Model page | Linear + Duolingo | 5.5 | 8 | Long explanatory sentences under Status; a one-point bankroll line says little. |
| Kennels index | Duolingo | 5 | 8 | Only one public kennel exists, so the page leans on the breeds legend. |
| Public kennel | Duolingo | 5 | 8 | |
| My kennel | Duolingo | 6.5 | 8.5 | Mock-owner capture. |
| Studio | Duolingo character creator | 6 | 9 | Breed is not choosable (it is the dog's vibe; the server does not store one). |
| Builder | Linear | 6 | 8 | The colour/badge pickers are the chart identity, a different palette from the dog's look; kept because they are saved data. |
| Training camp | Linear | 4 | 7.5 | Each section is now a card with a real heading, but the copy is long by design (it is the honest explanation of the learning loop). Stopped here: shortening it would change claims, not presentation. |
| Member app | Linear | 4 | 7 | Only the sign-in wall is capturable without an invite token. The app bar still stacks under the shared nav; its section labels are written in capitals by script. |
| Admin | Linear | 4.5 | 6.5 | Only the sign-in screen is capturable; the dashboard tables are untouched beyond tokens, faces, buttons and radii. |

Iterated and re-captured after the first scoring pass: model page (scoreboard cards, section cards, empty chart), builder (step cards,
the dog preview), kennels (new-kennel card, breeds legend), landing (pricing note was clipped, sample rows), camp (heading cards).
Pages that stay under 8 are the ones whose remaining gap is content or gated, not styling; that is said above, not hidden.

## Files

`web/css/lh.css` (tokens, components, dog rig CSS, choreography), `web/css/studio.css` (character creator, page touch-ups),
`web/css/landing-v2.css`, `web/css/lh-app.css`; `web/js/dog-look.js`, `dog-rig.js` (`renderDog`), `dog-avatar.js`, `dog-locker.js`,
`landing-race.js`, `lh-gate-dog.js`; tests `test_dog_rig.py`, `test_landing_race.py`, `test_no_horizontal_overflow.py` (+ `overflow_390.mjs`).
