# Model routing policy

**Owner directive, 2026-09-04. Effective immediately.** Governs every lane
dispatch in this project. Where an older doc or habit conflicts, this wins.

## Core principle

**Use the cheapest model that can do the work correctly.** Maximum completed
work per premium-model token, without sacrificing correctness.

Haiku for simple. Sonnet for most real work. Opus only for the hard stuff.
Fable orchestrates all of it.

## Fable is the orchestrator

Fable coordinates the project, decides priorities, assigns work, reviews
outputs, synthesizes results, and decides when escalation is justified.

Fable does **NOT** personally perform routine implementation, repetitive
inspection, bulk debugging, file searches, test sweeps, data transforms, or
anything else that can be delegated.

## Default routing order

### 1. Haiku — first for simple work
Simple file reads; basic searches; extracting facts; formatting;
straightforward documentation edits; small mechanical code changes; simple
test fixes; status checks; basic comparisons; repetitive low-reasoning tasks.

If Haiku can reliably do the task, use Haiku.

### 2. Sonnet — the default serious worker
Normal implementation; debugging; refactors; test creation; data pipelines;
APIs; repository inspection; feature implementation; moderate architecture;
analysis requiring real reasoning; multi-file changes; integration work.

**Most engineering happens here.**

### 3. Opus — targeted escalation only
Opus is NOT the default worker. Dispatch Opus only when the task genuinely
requires: difficult architecture; deep statistical/methodological reasoning;
adversarial review; complex debugging *after the issue has been isolated*;
security-sensitive reasoning; large synthesis beyond lower tiers; genuinely
difficult research judgment.

Opus receives a **focused task and an evidence packet**. Do NOT have Opus
rediscover an entire repository when Sonnet can first summarize the relevant
files, failures, logs and the open question.

**A large task alone does NOT justify Opus. Complexity and reasoning
requirement justify Opus.**

### 4. Deterministic tools before model tokens
Prefer code/scripts for backtests, simulations, large searches, statistics,
bulk file comparisons, repetitive validation, data joins, test matrices, log
parsing, enumeration.

**If Python or bash can answer it exactly, do that instead of spending model
reasoning tokens.**

## Escalation flow

Default: `Haiku -> Sonnet -> Opus`. Skip levels only when clearly warranted.
Fable remains above this chain as orchestrator/reviewer.

```
Fable assigns task
  -> Haiku gathers facts
  -> Sonnet implements/analyzes
  -> Opus reviews only the hard unresolved piece
  -> Fable synthesizes and decides
```

## Background agent policy

Every worker gets, explicitly, in its brief:

- a **narrow mission**
- an **explicit deliverable**
- an **expected effort/budget**
- a **stop condition**

Workers must **not endlessly retry**. If blocked: stop; report evidence;
identify the exact blocker; recommend escalation if needed. Then Fable
decides what happens next.

## Note on this repository's agent definitions

`.claude/agents/` currently defines worker types named `opus-*`
(opus-builder, opus-data, opus-research, opus-redteam, opus-validator,
opus-product). Those names describe the ROLE, not the required model. Under
this policy a dispatch must set the model explicitly to the cheapest tier
that fits, rather than inheriting Opus from a name. Prefer the role whose
description matches the work, and set `model` per the routing order above.
