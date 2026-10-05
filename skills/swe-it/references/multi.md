# Multi Dispatch

Use multi dispatch only after lane overlap checks pass.
After rendering the prompts, the agent using `swe-it` must
run the `multi-swe-day` workflow unless the contract mode is
`needs_human`.

The prompt emitted by `swe-it` must include:

- One leader prompt for `multi-swe-day(<work_item>)`.
- One builder prompt per candidate lane.

The bundled program renders no auditor prompt. Add one
when the plan calls for independent review or the run
changes shared execution protocols.

Each builder prompt must include:

- Lane label.
- Owned D rows.
- Owned target surfaces.
- Explicit off-limits surfaces.
- Validation commands.
- Reporting contract back to the leader.

The leader owns shared joins, final validation, reconcile,
and human gates forwarded from the contract. Builders must
not write shared state artifacts unless the leader prompt
assigns that surface to them.

The leader also owns ambiguity retirement, code-review,
address-comments, any l8 auditor pass, and final
clean-HEAD verification after all lane commits are
reconciled. Builders may resolve local implementation
ambiguity inside their owned lane, but they must report
decisions back to the leader before reconcile.

The leader must run final verification in a temporary
detached worktree at committed `HEAD`. If a lane forgot to
commit a needed source file, generated artifact, or
dependency input, the leader routes that failure back into
implementation and reruns verification after the fix lands.
