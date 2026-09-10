---
name: publication-truth
description: Fires automatically before claiming anything works, before reporting shipped or verified work, before a demo or a reviewer looks at the site, and whenever a result looks better than expected. Checks what the product is CLAIMING right now against the world, rather than whether the code does what was intended. Use when about to say "it's live", "it's working", "verified", "everything checks out", "picks are good", when someone external is about to see the output, or when a metric fires more often than it should.
---

# Publication truth

## Why this exists

2026-09-09. The site published 23 picks. 21 were for games already in
progress or final. One sat next to a game at 8-0 wearing a STRONG evidence
badge. A customer found it. Nobody here did.

That day was not under-verified. Mutation tests ran on the tier function, the
join key, the class filter, the dedup, the cadence gate. The live DOM was
read four separate times. Every one of those checks asked the same question:

> **Does this code do what I intended?**

A slip full of finished games passes all of them. Nobody asked the question
the reader asks first:

> **Is what is on the page true right now?**

That is the only question this skill is about.

## Fire on these, without being asked

- About to say **"it's live" / "it's working" / "verified" / "everything
  checks out" / "the picks are good"**
- About to **report shipped work** or summarize a session's results
- **Anyone external is about to look** — a reviewer, a demo, a customer, a
  screenshot going into a message
- A **result is better than expected**, or a metric designed to be rare is
  firing often
- Something was just **republished, redeployed, or backfilled**

## Do this

**1. Run the machine check first. It is stronger than any reasoning here.**

```bash
python scripts/publication_audit.py
```

Exit 1 means findings. It re-derives every claim independently instead of
importing the function that produced it — a check that calls the code under
test is an echo, not an audit. It covers: published picks on games that
already started, a rare tier firing at scale, families past the documented
ceiling, stale slips, and picks on markets no genome can express.

**2. Then check the claims the script does not cover yet.** For each surface
a reader will actually look at, ask what it is asserting and verify that
assertion against the world:

| Surface | The claim | How to falsify it |
|---|---|---|
| a pick card | "bet this now" | is that game still unplayed? |
| a record strip | "this is our record" | recount the ledger directly, cohort by cohort |
| an evidence badge | "N independent systems agree" | are they independent, or near-duplicate genomes? |
| a headline number | "this is measured" | grep for it as a hardcoded constant |
| anything price-derived | "this is value" | is it edge, or execution quality mislabelled? |

**3. Look at the page as the reader, not as the author.** Not "did my CSS
apply" — *read the sentences and ask whether each one is currently true.*
Screenshotting a card and checking its font while the game is over is the
exact failure this skill exists to prevent.

## The reasoning rules

**A surprise is an alarm, not a discovery.** The first instinct on seeing 11
families where the documented ceiling was 3 was to reason about how a bigger
population *might* justify it. That instinct is the bug. When something is
better or larger than the design says it can be, the prior is a measurement
fault, and it stays that way until proven otherwise in writing.

**Delight is a bug report.** In a product with zero confirmed edges, a reader
being *impressed* means something is overclaiming. Treat "that's a great
pick" from outside exactly like an error report.

**A number that got better without a reason is a defect.** Improvement with
no identified cause is unexplained behaviour, not good news.

**Building more is not verifying.** Knowing a reviewer is about to look and
responding by shipping another feature instead of opening the page is how
this happened. When a human is about to see it, go see it first.

**A losing pick is fine. A false one is not.** The product is allowed to be
wrong about the game. It is never allowed to be wrong about what it is
currently recommending.

## Reporting

Say what was checked and what came back, including "the audit found nothing"
as a distinct statement from "I looked at it." Never report work as verified
on the strength of tests alone — tests pin intent, and the same slip that was
true at 19:00Z is a lie at 23:30Z with no code change at all.
