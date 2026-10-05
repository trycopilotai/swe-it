#!/usr/bin/env python3
"""Record the contract session again and refresh the evidence manifest.

    python3 scripts/record_session.py

The commands are the ones listed in ``evidence/demo-manifest.json``.
They run in a throwaway directory that holds a copy of ``skills/``, the
plan in ``PLAN`` below at ``plans/greeting.md``, an empty ``state/``
directory, and a git repository named ``repo`` with one commit and one
uncommitted file, ``greeting.py``. The transcript is what a shell would
show: each command line, the output, and the exit status. One edit is
made before it is written: the throwaway directory's absolute path is
replaced with ``/work``.

The manifest's hashes of ``SKILL.md``, the program and the transcript
are then rewritten, with the date and the interpreter. Run ``make demo``
afterwards to rebuild the images.

Set ``RECORD_RAW_DIR`` to also keep the unedited capture and the
replaced path, outside the repository. The commit id and the temporary
worktree's name are published as recorded.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "demo-manifest.json"
PLACEHOLDER = "/work"
PLAN = """# Add a greeting

## Success Criteria

- `greeting.py` prints a greeting.
"""
GREETING = 'print("hello")\n'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(workdir: Path, environment: dict) -> None:
    """The plan, the state directory, and the repository the session uses."""
    shutil.copytree(
        ROOT / "skills",
        workdir / "skills",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in ("plans", "state", "tmp", "home"):
        (workdir / name).mkdir()
    (workdir / "plans" / "greeting.md").write_text(PLAN, encoding="utf-8")
    repo = workdir / "repo"
    for arguments in (
        ["init", "--quiet", str(repo)],
        ["-C", str(repo), "commit", "--quiet", "--allow-empty", "-m", "Start"],
    ):
        subprocess.run(["git", *arguments], check=True, env=environment)
    (repo / "greeting.py").write_text(GREETING, encoding="utf-8")


def record(commands: list[str], workdir: Path, environment: dict) -> str:
    define, steps = commands[0], commands[1:]
    lines = ["$ " + define]
    for step in steps:
        result = subprocess.run(
            ["bash", "-c", define + "\n" + step],
            cwd=workdir,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lines.append("$ " + step)
        lines.extend(result.stdout.splitlines())
        lines.append('$ echo "exit status: $?"')
        lines.append("exit status: %d" % result.returncode)
    return "\n".join(lines) + "\n"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    commands = manifest["invocation"]["commands"]
    with tempfile.TemporaryDirectory() as scratch:
        workdir = Path(scratch).resolve() / "capture"
        bindir = workdir / "bin"
        bindir.mkdir(parents=True)
        (bindir / "python3").symlink_to(sys.executable)
        environment = {
            "PATH": "%s:/usr/bin:/bin" % bindir,
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(workdir / "tmp"),
            "HOME": str(workdir / "home"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Example",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Example",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        prepare(workdir, environment)
        raw = record(commands, workdir, environment)
        capture_root = str(workdir)

    raw_dir = os.environ.get("RECORD_RAW_DIR")
    if raw_dir:
        Path(raw_dir, "contract-session.source.txt").write_text(raw, encoding="utf-8")
        Path(raw_dir, "contract-session.capture-root.txt").write_text(
            capture_root + "\n", encoding="utf-8"
        )

    transcript = ROOT / manifest["output"]["path"]
    transcript.write_text(raw.replace(capture_root, PLACEHOLDER), encoding="utf-8")

    manifest["date"] = datetime.date.today().isoformat()
    manifest["invocation"]["interpreter"] = "Python " + platform.python_version()
    manifest["skill"]["sha256"] = sha256(ROOT / manifest["skill"]["path"])
    for program in manifest["programs"]:
        program["sha256"] = sha256(ROOT / program["path"])
    manifest["output"]["sha256"] = sha256(transcript)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("wrote %s" % transcript.relative_to(ROOT))
    print("wrote %s" % MANIFEST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
