# Landing page: mobile conversion review, 2026-10-02

Reviewed the deployed page (`linehound-prod.fly.dev/web/landing.html`) at
390 x 844, as someone who has never heard of LineHound. No redesign: each
change below names the conversion problem it solves. There is no traffic yet,
so nothing here is measured against visitors; the measures are positions on
the page and, once outreach starts, `landing_view -> cta_click ->
signup_started` by source.

## What a stranger knows after five seconds (today)

First screen: "Every pick posted before the game. Every loss kept on the
record.", a paragraph about when grading happens, a button "Get notified
when checkout opens", then a panel: 16-17, -5.05 units, "CURRENT RULE".

| Question | Answered on the first screen? |
|---|---|
| What is it? | No. It says how we behave, not what the product is. |
| What do I get today? | No. First stated 1,163 px down (second screen and a half). |
| Which sports? | Yes (kicker line). |
| What is proven? | Partly: the method. |
| What is experimental? | No. 2,033 px down. |
| Why trust the record? | Yes. It is the headline. |
| What should I do next? | Unclear: the button is about our checkout, not their next step. |

The page leads with the trust evidence. The trust evidence is strong, but it
is support for an offer the page has not made yet.

## Changes, in order of expected effect

1. **Headline says the product; the method becomes the second sentence.**
   Problem: a visitor cannot tell what is being offered. Proposed headline:
   "Tonight's MLB, NFL and UFC bets, posted before the game." Lede: "A short
   card each night: the bet, the best price and where to find it, and why.
   Every card is graded in public afterwards, wins and losses." No result is
   promised and no edge is claimed.

2. **The button names the visitor's next step.** Problem: "Get notified when
   checkout opens" is about our billing state; "checkout" means nothing to
   someone who has not decided to buy. While billing is off: "Join the
   waitlist", with the note "Not on sale yet. Planned price $19.99 a month.
   The record and the postseason odds are free now." The second button
   becomes "See last night's card, graded" (the free sample), which is the
   only thing a stranger can try today.

3. **"What you get" moves directly under the buttons, as three lines.**
   Problem: the first thing under the buttons is a negative number with
   internal labels; the offer itself is on the third screen. Free now: the
   full graded record, MLB postseason odds. Subscribers: tonight's card
   before the game, with matchups, odds and props.

4. **The record panel stays on the first two screens, in plain words.**
   Problem: "CURRENT RULE" and "PREVIOUS RULE (RETIRED)" are our vocabulary.
   Proposed: "Since Sept 22 (current method)" and "Sept 10 to 22 (earlier
   method, retired)". The numbers, including the negative one, do not move
   down the page relative to today's second screen and do not shrink.

5. **One line separating what is proven from what is not, near the top.**
   Problem: a quick reader blurs "the record is honest" with "the picks
   win". Proposed, under the record panel: "Proven: every pick is published
   before the game and never edited. Not proven: that the picks make money."

6. **Pricing moves up; three sections that repeat the trust point merge.**
   Problem: the page is 12 phone screens; price is on screen 9, after "How it
   works", "A pick we got wrong" and "Why we publish the losses", which make
   one point three times (1,700 px). Keep "A pick we got wrong" (the concrete
   one), fold the other two into "What is proven and what is not", and put
   Pricing right after the free sample.

7. **One footer.** Problem: two stacked footers take 1,400 px on a phone
   after the final button.

## Decision for Brey (not made here)

Whether the first sign-ups get free tester access while billing is off. If
yes, the button can honestly say "Get free tester access" and people have
something to use and react to today, which is what the first-customer work
needs most. If no, "Join the waitlist" is the accurate label. Staging
already serves the paid pages free; production does not.

## Not changing

The negative record stays on the page at the same size. No win rate or
profit claim is added. Bet Check stays unadvertised. The cautious wording
when `/meta` has not loaded stays.
