# D-Day Timeline

`swe-it` uses D labels as execution-order markers. A D-day
is not a calendar promise unless the source plan explicitly
includes a calendar date or window.

## Row Shape

Each timeline row has:

- `label`: `D01`, `D12`, or another D-number found in the
  plan.
- `title`: Short row title derived from the source line or
  generated from the plan bullet.
- `dependencies`: Prior D labels that must land first.
- `target_surfaces`: Files, directories, or subsystems named
  in the row.
- `success_criteria`: Criteria copied from the contract. The
  program extracts no narrower criteria for a row, so every
  row carries the contract's list.
- `validation_commands`: Commands copied from the contract.
  The program extracts no narrower validation for a row, so
  every row carries the contract's list.
- `status`: `planned`, `in_progress`, `in_review`, or
  `done`.
- `calendar_window`: Empty unless the source row includes an
  explicit date or window. The program fills it from a
  loose text pattern, which also matches a word that starts
  with a month abbreviation and is followed by a number,
  such as `decision 3`.

## Derivation

When a plan already includes D labels, preserve them and
keep their original ordering. On a line that mixes a range
with single labels, the program puts the range's rows
first. When a line contains a range
such as `D18-D20` or a chain such as `D18→D19→D20`, expand
it into one row per label and give each row a title taken
from the same source line.

When a plan has no D labels, generate `D01`, `D02`, and
later labels from implementation bullets. Generated labels
are only local execution rows for the contract; they are not
project milestones.

## Dispatch

`swe-it(D12)` resolves `D12` from the current contract
timeline; pass it to `contract` as `--day D12`.
It must stop with `needs_human` when no row exists
for the selected label. The selector filters the contract's
`timeline` and `candidate_lanes` only. `target_surfaces`,
the success criteria and the validation commands still
cover the whole plan, and the solo prompt does not name
the selected row, so tell the downstream run which row it
is.

Adjacent D rows can share one lane when they own the same
surface and are ordered by dependency. Independent rows can
become separate lanes only when primary surfaces do not
overlap.
