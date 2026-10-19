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
