---
name: debrief
description: Catch Brey up on what happened since he was last here, in plain language. Use when he says "debrief me", "get me up to speed", "what happened", "summarize the last work", "/debrief", or comes back after being away. Also use after any long autonomous run before going idle.
---

# Debrief

Brey has been away. He does not remember the details, does not want the
details, and has asked more than once — emphatically — to stop being buried in
words. This skill exists because the debriefs kept coming out too long and too
technical anyway.

## The rule

**Under 200 words. No exceptions without asking first.**

If you think this one genuinely needs more, say so in one line and ask. Do not
just write more.

## Write it like this

Plain English. A smart friend who does not code and did not read the repo.

- "We tested 8 betting ideas. None of them made money." — good
- "Zero of 8 detectors cleared FDR and effect-size gates." — bad
- Numbers only when the number is the point. One or two, not a table.
- No jargon: no FDR, p-values, clustered bootstrap, point-in-time, autocorrelation.
  If a concept matters, describe what it *means* — "we checked it wasn't luck."
- No file paths, function names, commit hashes, or test counts.
- Never use an artifact. Plain text in chat.

## Structure

Four short beats, in this order. Headers optional — often it reads better as
four short paragraphs.

1. **What I did** — one or two sentences.
2. **What I found** — the actual result, including bad news, stated first and
   plainly. If nothing worked, lead with that.
3. **What it means for you** — so what? why should he care?
4. **What's next / what I need** — any decision waiting on him, as a direct
   question. If nothing is blocked, say the work continues and stop.

## Non-negotiables

- **Lead with bad news.** Never bury a null result under activity. "We built a
  lot of stuff" is not a finding.
- **Never imply an edge exists.** As of the last two research families, none
  does. If that ever changes it changes because evidence changed, and the
  debrief says exactly what the evidence is.
- **Losers get reported.** Same rule as the research itself.
- **Don't inflate effort into progress.** Lines of code and passing tests are
  not results and do not belong here.
- If a question is waiting on him, it goes last and it is one question, not a
  menu — unless the options genuinely change what happens next, in which case
  use AskUserQuestion.

## Checklist before sending

- Under 200 words?
- Would someone who has never seen this repo understand every sentence?
- Is the most important fact — usually the disappointing one — in the first
  two sentences?
- Any jargon that slipped through?
- Is there exactly one clear ask, or none?
