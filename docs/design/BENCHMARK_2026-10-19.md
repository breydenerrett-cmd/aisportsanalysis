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

---

# Round 2: the independent critic's ten asks, and an honest before/after

An independent critic scored the round-1 rebuild (`docs/design/after/`) and asked for ten changes, ranked. All ten were done; the
re-captures are in `docs/design/after-r2/` (same pages, same local read-only proxy of the public API, same headless browser, same
mock owner for My kennel and the studio). Presentation only: no rule, record, price, API meaning or claim changed.

Capture note. A full-page screenshot draws a `position: fixed` bar once, over mid-page content, so the round-1 phone shots showed the
tab bar sitting on the podium and on the model page's bankroll tile. That part was a capture artefact, not a layout bug (the page already
padded 62px). The r2 capture pins the bar to the end of the document, which is where a visitor sees it, and the page now leaves the bar's
height plus 24px plus the home-indicator inset (a real-browser test measures it on every page).

## What changed, per ask

| # | Ask | What was done | Measured |
|---|---|---|---|
| 1 | Landing: three sections, accordions | Below the hero: build-your-dog band, "How it works" in three steps (a house dog on each), the AI desk as one compact card. Free-versus-subscribers, the last graded card (the fills table), pricing and the per-sport record tiles are closed native `<details>`; a link to `#pricing` opens its accordion. Every data-hook the fills write into is still there. | 1440: 4,732px. 390: 7,095px (the original audit measured about 10,000px; the round-1 phone shot was capped at 6,000px so it cannot be compared directly). The hero, the board and the ticket list are most of what is left on a phone. |
| 2 | Camp: stat strip, collapsed sections | Four figures on top (coach tips graded, helped / hurt, next breeding cycle, your dogs in training); ten sections each a closed card with its headline and one number; the long copy stays behind each section's own "How this works". A figure the server did not send is a dash, never a zero. | 1440: 4,757px to 1,397px. 390: 1,929px (round-1 shot capped at 6,000px). |
| 3 | Dog art | 25 breed silhouettes (ears pointed, floppy, folded, rose, puffs; snout length; head shape; markings: blaze, mask, spots, patch, tan points, ruff, beard, topknot). The breed now comes from the dog's name first (a Chihuahua is a Chihuahua whatever its vibe), then its vibe, then a hash of its id; the label is read from the same mapping, so the two cannot disagree. Professor Paws wears glasses. | 27 house dogs checked in a test; `dog-breeds-gallery.png` and `dog-house-roster.png`. |
| 4 | Model page | The bankroll is one wide hero tile (big dollar figure, the return beside it, small 24h / 7d / 30d / Season tabs); the other seven are one secondary row; Fire now is a full-width bar. | Same numbers, hooks and document order. |
| 5 | Leaderboard | Under 1500px the 7d, 24h, average-price and last-10 columns are hidden; from 1500px the page widens and all 13 show; a still-too-wide table scrolls inside its card with rank and model pinned. The empty "Ranked (0)" table is not drawn while the qualifying round leads. A long model meta line wraps (it held the model column at 434px and was the real cause of the clip with live data). | A headless-Chrome test measures the table at 1440 and 1600: no sideways scroll. |
| 6 | Phone tab bar | `--lh-tabbar-h` plus 24px plus `env(safe-area-inset-bottom)` as body padding on every page that draws the bar. | Measured at 390 on every page (clearance at least the bar's height). |
| 7 | Kennels | A featured-dog card (says why it is featured, says "small sample" under 20 settled bets), the latest tickets from member dogs, a thinking dog for the empty states; the breeds legend is gone. | Kennels 1440: 900px to 1,412px of real content; public kennel 889px to 1,621px at 390. |
| 8 | Builder | A 176px live dog: a breed word in the name picks that breed, the coat follows the name, the backdrop follows the colour, the pose follows how much has been said. Each swatch is drawn as the dog backdrop nearest in hue (the colour itself stays the ring). A new dog is saved with the look that was in the preview (a best-effort cosmetic PUT). Each sidebar card has a dog. | `builder-typed-1440.png` shows "Husky Harry" as a husky on a blue backdrop. |
| 9 | Sign-in walls, labels | The admin sign-in has Professor Paws and a "Back office" line (a snapshot of the rig in the markup, because that page keeps exactly one script); the member gate dog is bigger. Tab bar labels, gate eyebrows, the shell status line, the state-card eyebrows and three Gameday links are sentence case in the source. | |
| 10 | My kennel | The four actions are a 2x2 grid on a phone (Open was an orphan); stat labels are 13px and brighter. | `kennel-mine-390.png`. |

Also fixed on the way: a count-up started every number at zero, so a screenshot caught "$73.14" on a $1,000 account. A bankroll now counts
from $1,000 toward its value (or does not move when equal), and a hidden tab or reduced motion shows the final number at once.
"Small sample.. Settled" on the bankroll tile had a double full stop.

## Scores, same 1-10 scale (8 = could sit next to the reference)

| Page | Round 1 | Round 2 | What is still short |
|---|---|---|---|
| Landing | 8 | 8.5 | The first screen and the board still carry a lot on a phone; the dog faces are stylised vector art, not the hand-drawn character a studio would commission. |
| Leaderboard | 8 | 8.5 | 13 columns only fit at 1500px and up; under that, four are hidden by design. |
| Model page | 8 | 8.5 | Long explanatory sentences under Status; a one-point bankroll line says little. |
| Kennels index | 8 | 8 | One public kennel exists, so the featured dog and the strip carry a page whose real content is two dogs. |
| Public kennel | 8 | 8 | Same. |
| My kennel | 8.5 | 8.5 | Mock-owner capture. |
| Studio | 9 | 9 | Unchanged apart from the breed label now matching the dog. |
| Builder | 8 | 8.5 | The saved chart colour is still its own palette; the preview and swatches speak the dog's, but they are two things. |
| Training camp | 7.5 | 8 | The sections hold the same long honest copy; it is behind a click now, not shorter. |
| Member app | 7 | 7.5 | Only the sign-in wall is capturable without an invite token. Hundreds of capitals-in-source labels in the Gameday, Matchups and Props views were not touched; only the tab bar, gates, status line, state cards and three Gameday links were. |
| Admin | 6.5 | 7 | Only the sign-in card is capturable; the dashboard tables are unchanged. |

Not done, on purpose: the landing keeps no "paper only, 21+" line in its body, because the owner's 2026-10-18 voice pass has the shared
footer say it once and a test holds that; the critic's "keep the hard lines" is met by the MLB pause note in the hero and the footer.
Tests that pinned capitals as the visual form of a label (`label: "GAMEDAY"` and the like) and the empty "Ranked (0)" table were updated
to the new form, not removed. A few breeds still read close to each other at 32px (greyhound and whippet in particular).

Round 2 files: `web/js/dog-breeds.js`, `camp-overview.js`, `kennel-extras.js`; `web/css/studio.css`, `landing-v2.css`, `lhnav.css`,
`lh-app.css`; tests `test_dog_rig.py`, `test_landing_sections.py`, `test_hounds_camp_overview.py`, `test_hounds_model_hero.py`,
`test_web_leaderboard_fit.py` (+ `table_fit.mjs`), `test_no_horizontal_overflow.py` (tab-bar clearance), `test_kennel_extras.py`,
`test_hounds_builder_preview.py`, `test_admin_gate_dog.py`, `test_web_count_up.py`.
