# swe-it Plan Contract

The contract is the durable interface between a saved plan
and execution dispatch. It is JSON so wrappers, prompts, and
tests can inspect it without reparsing prose.

## Fields

- `schema_version`: Integer contract version. The bundled
  program writes `3`.
- `plan_source`: Path, inline marker, or selector that
  identified the plan.
- `repo_root`: Target repository root supplied by the
  caller.
- `mode`: One of `solo`, `multi`, `m2`, or `needs_human`.
- `work_item`: Short human-readable title for the execution
  run.
- `success_criteria`: List of acceptance or completion
  statements. Bullets under a `Validation` heading are not
  copied here; their commands go to `validation_commands`.
- `timeline`: List of D-day rows.
- `target_surfaces`: Primary files, directories, or
  subsystems named by the plan.
- `off_limits`: Files, directories, systems, or behaviors
  the plan says not to touch. Backticks are removed from
  each entry, so `` `Makefile` `` becomes `Makefile`.
- `candidate_lanes`: Proposed lane objects. Each lane has a
  `label`, `title`, `days`, `target_surfaces`,
  `validation_commands`, and `dependencies`.
- `validation_commands`: Commands copied from the plan. Do
  not infer commands that are not present. The program
  copies a command only when it is one of `bazel`, `make`,
  `npm`, `npx`, `pnpm`, `python`, `python3`, `pytest`,
  `swift`, `uv`, `x`, or `xcodebuild` alone, or starts with
  one of them followed by a space, and it is a line of a
  code block fenced with three backticks anywhere in the
  plan, or a bullet or an inline code span under a heading
  that contains `test`, `validation`, or `verify`. A
  bullet's whitespace is collapsed before that test, so a
  tab after the word counts there; in a fenced line or an
  inline code span it does not. Under such a heading, bullets
  indented beneath a bullet that is not itself a command
  and contains `pattern` with `search` or `removed` are
  skipped. A validation command whose first word is any
  other word is not recognized. The copy
  is not exact: each run of whitespace in a command becomes
  one space, when the program copies it and again before
  `verify` runs it, so a command that depends on repeated
  spaces inside quotes is changed.
- `human_gates`: Operator approvals or review gates copied
  from the plan and forwarded to downstream execution. The
  program copies a line when, in any letter case, it
  contains `human gate` or `operator-gated`, or it contains
  `approval` or `approve` and not `without approval`. A
  line whose text, after any `-` or `*` bullet marker or
  `#`, starts in any letter case with `Status` and a colon,
  such as `Status: approved.`, is metadata and is never
  copied. A
  heading whose whole text is a generic gate title, such as
  `Human Gates` or `Approvals`, is not copied. The program
  misses a gate worded any other way, and it can copy a
  line that uses one of those words without being a gate.
- `ambiguities`: Ambiguity or open-question statements
  copied from the plan.
- `ambiguity_policy`: The downstream rule set for resolving
  ambiguity without stalling safe work.
- `review_closeout`: Required review, l8, human-review, and
  address-comments closeout checks.
- `final_verification`: Required final clean-HEAD verifier
  contract. It includes `clean_worktree_required`,
  `missing_file_detection_required`, copied
  `validation_commands`, optional `generated_artifact_checks`,
  `required_submodules`, and short execution instructions.
  `verify` runs the commands listed here. When this object
  has a `validation_commands` list, a command that is only
  in the contract's top-level `validation_commands` is not
  run.
- `blocking_questions`: Missing facts that prevent safe
  dispatch.
- `handoff_artifacts`: Suggested state artifacts for the
  downstream execution skill.

## Mode Rules

Use `needs_human` when any of these are true:

- The plan is not m2-shaped and does not state success
  criteria or acceptance criteria. The program reads that
  as: no bullet under a heading that contains `success`,
  `acceptance`, `criteria`, or `test plan`. A heading named
  only `Validation` does not count, so a plan whose only
  bullets sit under `Validation` is sent to `needs_human`
  for missing success criteria.
- The plan is not m2-shaped and does not name validation
  commands the program recognizes.
- Two or more candidate lanes overlap on a primary target
  surface.
- The requested D-day selector is not present in the
  timeline.

Use `multi` only when there are two or more candidate lanes,
each lane has primary target surfaces, and no lane owns the
same file/directory or an ancestor/descendant path of
another lane. The program compares surfaces as written, so
it does not see `src/a.py` and `./src/a.py` as the same
file.

Use `m2` when the plan is m2-shaped by filename,
invocation text, durable-conductor language, manager lanes,
budget modifiers, or final-response-gate language. The
program applies that as: the plan path ends in
`plan.m2.gpt.md`, or the plan text contains, in any letter
case, one of `m2(`, `manager-of-managers`,
`durable conductor`, `numM1s:`,
`acceptance-first planning`, or `final response gate`. Do
not block `m2` routing merely because success criteria or
simple swe-day validation commands are absent; m2 owns
acceptance-first planning and gate validation.

Use `solo` for a complete plan that is coupled, small, or
lacks enough surface detail to split safely.

## Final Verification

Every non-blocked route that changes files must validate the
committed `HEAD` from a temporary detached clean worktree
before final response. Validation in the original dirty
checkout is useful during implementation but is not final
evidence.

Clean-worktree failures caused by missing source files,
generated artifacts, or dependency inputs are implementation
failures. Fix and commit the missing input, then rerun the
final verifier. Do not treat those failures as operator
review gates unless the missing input is explicitly outside
the plan's scope or requires destructive/security-sensitive
action.
