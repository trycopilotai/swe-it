# Solo Dispatch

Use solo dispatch for coupled plans or plans that are
complete but not safe to split. After rendering the prompt,
the agent using `swe-it` must run the `swe-day` workflow
unless the contract mode is `needs_human`.

The prompt emitted by `swe-it` must include:

- `swe-day(<work_item>)`.
- The plan source and repo root.
- Success criteria.
- Target surfaces.
- Off-limits surfaces.
- Validation commands.
- Human gates.
- Ambiguities and ambiguity policy.
- Review closeout.
- Final clean-HEAD verification.
- Handoff artifacts.

Do not add validation commands, paths, or gates that are not
in the contract, except a gate the plan states and the
program's patterns missed.

After implementation commits, review, and address-comments
changes land, run the `swe-it` final verifier. The verifier
must use a temporary detached worktree at committed `HEAD`;
the solo run is not complete if only the dirty checkout has
passed.
