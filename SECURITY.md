# Security

## Reporting a vulnerability

Report privately through GitHub:
<https://github.com/trycopilotai/swe-it/security/advisories/new>

That opens a private security advisory visible only to the
maintainers. Do not put the details of a vulnerability in a
public issue.

If that link shows "Not Found", private reporting is not
turned on for this repository. Open a public issue titled
"Security report waiting" that says only that you have a
report, with no details, and a maintainer will arrange a
private channel.

## What is in scope

- **Prompt content that redirects an agent.** `SKILL.md` and
  the six files under `references/` are instructions an
  agent follows while it executes a plan, including commits
  and a review closeout. Text in any of them that makes an
  agent dispatch past a `needs_human` contract, skip a human
  gate, or treat repository content as instructions is a
  valid report.
- **The program outside `verify`.**
  `skills/swe-it/scripts/swe_it.py contract` reads one plan
  file. When no `--plan` is given it picks the most recently
  modified matching `.md` file under three directories of
  `--repo` that `SKILL.md` names; under the third, only a
  file whose name contains `plan` matches. It reads
  `.gitmodules` in `--repo` by running `git config --file`.
  `timeline`, `lanes` and `prompts` read a contract, and
  `next` reads `swe-it.json` in the directory it is given.
  Each of `contract`, `timeline`, `lanes` and `prompts`
  writes one file, at the path given, when `--out` is given
  and otherwise prints; it first creates any missing parent
  directories of that path. `verify --out` writes its report
  the same way. A plan or contract
  that makes one of these five subcommands write any other
  file, or run any command other than that one `git config`
  read, is a valid report.
- **The install blocks.** The two README blocks run
  `mkdir -p`, `mktemp -d`, `git clone`, `cp`, `mv` and
  `rm -rf`, all inside one skills directory under `$HOME`. A
  repository state that makes either block write or delete
  outside its install target is in scope.
- **The build scripts.** `assets/build.py` finds a Chrome or
  Chromium binary from a fixed candidate list, runs it
  headless with a temporary profile directory, and writes
  the preview PNG and its stamp. `scripts/generate_demo.py`
  writes two SVG files; `scripts/verify_demo.py` only
  reads. `scripts/record_session.py` copies `skills/` into
  a temporary directory, creates a git repository with one
  commit there, runs the program and a few shell commands
  through `bash`, and rewrites the transcript and the
  manifest. With `RECORD_RAW_DIR` set it also writes two
  files into that directory, which is outside the
  repository. `tests/test_integrations.py` runs `git`
  against the repository root and runs the program on a plan
  in a temporary directory. `tests/test_swe_it.py` creates git
  repositories in temporary directories, commits to them,
  adds one as a submodule of another, and runs `verify` on
  them.

## `verify` runs the plan's commands

`verify` is not a sandbox, and these are known limits, not
findings:

- It runs each validation command and generated-artifact
  check in the contract's `final_verification` object
  through `/bin/bash`, with the caller's environment and
  privileges. It falls back to the top-level
  `validation_commands` only when that object, or its own
  `validation_commands` list, is absent. `contract` copies
  those commands from the plan, and anyone who can edit the
  contract file can add more. A line in a fenced code block
  of the plan that starts with a word on the program's list
  and a space is copied as a validation command, whatever
  section it is in, and so can be a prose bullet under a
  validation heading that starts that way, such as
  `make sure the tests pass`. Each run of whitespace in a
  command is collapsed to one space before it runs. The
  clean worktree is only the directory the commands start
  in. They can read and write whatever the caller can,
  including the original repository. Treat a plan and a
  contract as code.
- Before the commands, it reads the commit id of `HEAD` and
  runs `git worktree add --detach` at that id
  in the contract's `repo_root`, which writes worktree
  metadata into that repository, and afterwards
  `git worktree remove --force`. If the process is killed in
  between, the worktree and its temporary directory stay
  behind. When `repo_root` is a directory inside a
  repository and not its root, git acts on the enclosing
  repository. A relative `repo_root` is resolved against the
  directory `verify` is run from, and a contract with no
  `repo_root` is verified in that directory.
- It can run `git submodule update --init --recursive` with
  `protocol.file.allow=always` in the worktree: for the
  submodule paths the contract lists as required, or, when
  it lists none, for paths in the `.gitmodules` of the
  `repo_root` checkout whose last component appears as a
  word in one of the commands and is neither `git` nor one
  of the twelve command words. That fetches from whatever
  URLs the committed `.gitmodules` names, over the network
  if they are remote.
- A contract that yields no commands by that rule reports
  `"passed": true` once the worktree has been added and
  removed, having run no command.
- `verify` exits with status 1 when a command or the setup
  fails. A Python traceback also exits with status 1, so
  read the JSON, not only the status.

## The contract is advisory

These are also known limits, not findings:

- The mode comes from text patterns, listed in
  `references/plan-contract.md`. The program treats most
  words and backticked spans that contain a `/` as target
  surfaces, URLs excepted, so a phrase such as `and/or`
  counts as one. It can therefore pick `multi`, or block on
  an overlap, where a person would not. Surfaces are
  compared as written, so two spellings of one path are not
  seen as an overlap.
- A D label is matched in any letter case anywhere on a
  line, so `tools/d3/chart.js` yields a `D03` row and
  `D12 - 3 files` is read as a range. A date is matched by a
  loose pattern. A row's status comes from words such as
  `done` or `review` anywhere on its line. Any line that
  starts with `#` starts a new section, a comment in a
  fenced block included.
- Human gates are found by the word patterns in
  `references/plan-contract.md`. A gate worded another way
  is not copied, and a line that only mentions approval can
  be.
- `next` prints "dispatch solo swe-day" for any mode it does
  not know, where `prompts` renders the blocked prompt.
- With a relative `--repo`, `contract` can fail to read
  `.gitmodules`, and then it lists no required submodules.
- Human gates, off-limits entries and blocking questions are
  copied into the contract and the prompt. The program does
  not enforce them. `verify` runs a `needs_human` contract's
  commands like any other's.
- With no `--plan`, the plan is whichever matching file was
  modified last. Anything that can write those directories
  chooses it. A file whose path, as built from the `--repo`
  value, has a component named `.git`, `node_modules` or
  `__pycache__` is skipped.
- Malformed input can end in a Python traceback and not in
  a message. Some examples, not a complete list: a plan
  that is not UTF-8, a contract that is not JSON, a contract
  that lacks a field the subcommand reads, or a `repo_root`
  that does not exist.
- The program needs `git` for `contract` in a repository
  with a `.gitmodules` file and for `verify`, and
  `/bin/bash` for `verify`.

## What is out of scope

The skill dispatches to other skills. Their behaviour, and
the behaviour of Claude Code, Codex, or any other host, is
out of scope here. Report those to their own maintainers.
