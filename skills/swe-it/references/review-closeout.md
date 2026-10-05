# Review Closeout

Every non-blocked `swe-it` execution route must include a
review closeout before final response:

- Run `code-review` over the final diff unless the run
  made no code, doc, config, plan, or generated-output
  changes.
- Run `address-comments` until `TODO(agent)`,
  `AGENT:`, and `TODO(code-review:<id>)` markers are
  resolved or blocked with owner, reason, and next action.
- Apply the `l8()` risk order to final review. For
  multi-lane, protocol, or long-running routes, include an
  l8 auditor pass.
- For human-review gates, build an ask-human-review style
  review surface, collect in-place comments, and then run
  `address-comments`.
- After review and address-comments changes land, run the
  `swe-it` final verifier against committed `HEAD` from a
  temporary detached clean worktree.

Do not advance behind an unmet human gate. Human-review
gates clear only when the operator provides the review
result or clears the gate through the downstream protocol.

Do not final-answer from dirty-checkout validation alone.
If clean-HEAD validation fails because files or generated
artifacts were never committed, commit the missing inputs
and rerun review closeout as needed before final response.
