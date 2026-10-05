# Contributing

This repository is one skill, one program with its tests,
and the scripts that build and check the demo images.

## Run the checks first

```sh
make check
```

That runs `tests/test_swe_it.py` and
`tests/test_integrations.py`. Both need `python3`, `git` and
`bash` and nothing else. The first creates git repositories
in temporary directories and commits to them. The second
needs a real clone with its history and tags, because it
reads `git log` and the release tag.

**The packaging contract asserts on the README.** These will
fail on an innocent-looking prose edit:

- the claim line at the top of the README must appear
  verbatim, and the mode it describes must be in the
  recorded transcript;
- each install block must carry its own `release=` pin at
  the version both plugin manifests ship;
- `SKILL.md` must stay under 500 lines;
- `evidence/demo-manifest.json` records the SHA-256 of
  `SKILL.md`, of the program and of the transcript, so any
  edit to one of those three files, prose included, fails
  until the manifest is refreshed as described next.

If you change one of those, change the thing it describes
too.

## Changing the program or the transcript

After any edit to `SKILL.md` or to the program, run:

```sh
make record
make demo
```

`make record` runs `scripts/record_session.py`. It replays
the commands listed in the manifest in a throwaway
directory, writes the transcript with that directory's path
replaced by `/work`, and rewrites the manifest's hashes,
date and interpreter. It needs `bash`, `git` and `python3`.
The transcript usually carries a new commit id, and carries
a new temporary directory name, each time, so it changes
even when the program did not. `make demo` rebuilds the two
images from the transcript. `make assets` rebuilds the social preview
and needs Chrome or Chromium; `make asset-check` does not.

## What is most useful

Open an issue for any of these. The labels
`good first issue` and `help wanted` mark the ones that are
ready to pick up.

- **A plan the program routes wrongly.** Attach the plan,
  with anything private removed, the mode the program chose,
  and the mode you expected.
- **A validation command the program does not recognize.**
  It recognizes a command by its first word, from a short
  fixed list. Say which first word you needed.
- **A run where an agent dispatched past `needs_human`.**
  Say what the contract's blocking questions were, what the
  agent did next, and which host ran it.

## Pull requests

Prose changes to `SKILL.md` and the files under
`references/` are welcome. Say what an agent did before the
change and what it does after, on the same plan.

Keep `SKILL.md` under 500 lines; the suite enforces it.
Frontmatter carries `name` and `description` and nothing
else.

The top-level `skill` is a symlink to `skills/swe-it/`. Do
not reverse that orientation.

Commit with your own identity and no `Co-authored-by`
trailer of any kind. The suite fails on one anywhere in
history, so do not apply review suggestions through the
GitHub UI.
