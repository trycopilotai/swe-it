---
name: swe-it
description: >-
  Execute an approved implementation plan end to end by
  building a deterministic SWE execution contract, optional
  D-day timeline, and immediate trycopilotai/swe-day,
  trycopilotai/multi-swe-day, or m2 durable-conductor
  dispatch. Use
  when the user says swe-it(...), swe-it(), asks to execute a
  saved plan or the most recent plan in chat, wants a plan
  converted into SWE work, wants D-day execution rows, or
  needs solo, multi-agent, or long-running m2 routing with
  final clean-HEAD verification.
---

# swe-it

Use this skill to execute the target plan through existing
SWE execution skills and protocols. `swe-it` is a router
over:

- Use `trycopilotai/swe-day` for short, mechanical, or coupled
  implementation runs.
- Use `trycopilotai/multi-swe-day` when the contract has safe
  disjoint lanes.
- Use `m2()`, from `trycopilotai/m2`, when the plan is
  explicitly m2-shaped, budgeted, multi-week,
  manager-of-managers, or needs a durable conductor loop.
- Stop at `needs_human` when the plan lacks success
  criteria, validation, ownership, or a safe dispatch shape.

The contract builder picks the `mode` from text patterns in
the plan, which `references/plan-contract.md` lists. It does
not judge size, coupling, duration, or ownership.

## Workflow

1. Read the user-provided plan, saved plan file, D-day
   selector, or most recent implementation plan in the agent
   chat. If no argument is present and no chat plan is
   available, use the latest saved plan under `plans/`,
   `.agents/plans/`, or `.agents/projects/`.
2. Run the contract builder:

```bash
python3 scripts/swe_it.py contract \
  --plan <path-or-text> \
  --repo <repo-root> \
  --out <contract-json>
```

   `<contract-json>` is a file outside the target repo; the
   later steps read it. `scripts/swe_it.py`, here and below,
   is relative to this skill's directory, not to the target
   repo.

3. If the contract mode is `needs_human`, stop and present
   only the blocking questions.
4. If the user requested timeline planning, run:

```bash
python3 scripts/swe_it.py timeline --contract <contract-json>
```

5. Render the downstream dispatch prompt:

```bash
python3 scripts/swe_it.py prompts --contract <contract-json>
```

6. Immediately follow the emitted `swe-day(...)`,
   `multi-swe-day(...)`, or `m2(...)` prompt. Do not answer
   with the prompt alone.
7. Before final response, run the final verifier after all
   implementation and review-addressing commits land:

```bash
python3 scripts/swe_it.py verify --contract <contract-json>
```

8. Continue until the downstream execution skill reaches a
   human-review gate, blocks with owner/reason/next action,
   or completes with clean-HEAD verification passing.

## References

- Read `references/plan-contract.md` before changing
  contract fields or interpreting `needs_human`.
- Read `references/timeline.md` before using or modifying
  D-day behavior.
- Read `references/solo.md` before dispatching a solo
  `swe-day` run.
- Read `references/multi.md` before dispatching a multi-lane
  run.
- Read `references/m2.md` before dispatching a durable
  conductor run.
- Read `references/review-closeout.md` before changing the
  review, l8, address-comments, or human-review gates.

## Rules

- Treat D labels as dependency-order labels unless the
  source plan gives explicit calendar dates.
- A D-day selector, passed to `contract` as `--day`,
  filters the contract's timeline and lanes only. The
  dispatch prompt still carries the whole plan's target
  surfaces and does not name the selected row; tell the
  downstream run which row it is.
- Keep repo-specific commands and state paths in wrappers or
  plans, not in the generic upstream skill.
- Never invent validation commands. If a plan that is not
  m2-shaped does not name validation, return `needs_human`.
- Forward human gates into the downstream dispatch instead
  of treating them as `swe-it` blockers. The program copies
  only the gate lines its patterns match
  (`references/plan-contract.md`); add any gate it missed
  to the dispatch yourself.
- Carry an ambiguity register into downstream execution.
  Resolve implementation ambiguity through repo discovery,
  tests, and reversible choices. Stop only for high-impact
  intent, destructive scope, security/privacy boundaries,
  missing acceptance, missing validation, or explicit
  human-review gates.
- Every route must end with code-review and
  address-comments unless no files changed. Multi-lane,
  protocol, or long-running routes also require the l8 risk
  lens.
- Every route that changes files must validate committed
  `HEAD` in a temporary detached clean worktree before final
  response. Dirty-checkout validation is not sufficient.
- Treat clean-worktree build/test failures from missing
  source files, generated artifacts, or dependency inputs as
  implementation failures to fix and recommit before final
  response.
- Never mutate the target repo while building contracts,
  timelines, lanes, prompts, or next-action output. Once
  dispatch starts, mutate only under the downstream
  `swe-day`, `multi-swe-day`, or `m2` rules.
