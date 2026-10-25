# ChatGPT: reviewer and research helper (not a co-commander)

ChatGPT reads this repo through its GitHub connector. It reviews, researches and proposes changes. Claude decides what gets built and is the only one that edits code. Brey has the final say.

## What ChatGPT does
- Review code, hound rules, grading and research files, and point out bugs, risks and weak reasoning.
- Run Deep Research on sports, markets, injuries and methods.
- Propose changes and tweaks with evidence.

## What ChatGPT does not do
- Edit code, open pull requests or push. It reads and writes proposals only.
- Present a guess as a fact, a price without a timestamp, or a probability without saying where it came from.

## How to hand off
Save each review or research note here as `docs/chatgpt/YYYY-MM-DD-<topic>.md`, using this template, or paste it to Claude.

```
# <topic>: ChatGPT proposal, <date> <time PT>
Type: review | research | proposal
Files/areas looked at: <paths>

## Findings
1. <finding> | evidence: <file:line / source URL / screenshot> | label: [VERIFIED] [SOURCE-CLAIM] [MODEL] [UNVERIFIED]

## Proposed changes (each one small and testable)
1. <change> | why | how to test it | risk if wrong

## Prices/odds mentioned
<book, market, price, timestamp>. These are history, never executable later.

## Open questions for Brey or Claude
```

## What Claude does with it
- Checks every claim against LINEHOUND's own data and code before acting on it.
- Builds the accepted proposals, says which were declined and why, and records both in docs/BACKLOG.md.
- Keeps every pregame record frozen: no proposal can change what a hound knew before a game.
