#!/usr/bin/env python3
"""Tests for swe_it.py."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "swe-it"
    / "scripts"
    / "swe_it.py"
)
SPEC = importlib.util.spec_from_file_location("swe_it", SCRIPT_PATH)
if SPEC is None:
    raise RuntimeError("failed to load swe_it.py spec")
MODULE = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("failed to load swe_it.py loader")
sys.modules["swe_it"] = MODULE
SPEC.loader.exec_module(MODULE)


class SweItTest(unittest.TestCase):
    def _plan_file(self, text: str) -> str:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "plan.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _git_repo(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        subprocess.run(["git", "init"], cwd=str(root), check=True, capture_output=True)
        (root / "required.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "required.txt"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Example",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                "Initial commit",
            ],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        return root

    def _commit_all(self, root: Path, message: str) -> None:
        subprocess.run(["git", "add", "."], cwd=str(root), check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Example",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-m",
                message,
            ],
            cwd=str(root),
            check=True,
            capture_output=True,
        )

    def test_contract_needs_human_without_validation(self) -> None:
        plan = self._plan_file(
            """# Small Change

## Success Criteria

- The feature exists.
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(contract["mode"], "needs_human")
        self.assertIn(
            "missing validation commands",
            contract["blocking_questions"],
        )

    def test_generates_d_day_timeline_from_bullets(self) -> None:
        plan = self._plan_file(
            """# Build Tool

## Implementation Changes

- Add `tools/cli/main.py`.
- Add `tools/cli/tests/test_main.py`.

## Success Criteria

- The CLI dispatches commands.

## Validation

- python3 -m unittest discover
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual([row["label"] for row in contract["timeline"]], ["D01", "D02"])
        self.assertEqual(contract["mode"], "multi")

    def test_preserves_d_labels_and_calendar_windows(self) -> None:
        plan = self._plan_file(
            """# Timeline Plan

## Implementation Changes

- D12 on 2026-07-09: close `src/vehicle/app.py`.
- D18-D20 Jun 22-24: build `src/rules/catalog.py`.

## Success Criteria

- All rows land.

## Validation

- pytest
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        labels = [row["label"] for row in contract["timeline"]]
        self.assertEqual(labels, ["D12", "D18", "D19", "D20"])
        self.assertEqual(contract["timeline"][0]["calendar_window"], "2026-07-09")
        self.assertEqual(contract["mode"], "multi")
        self.assertEqual(contract["validation_commands"], ["pytest"])
        self.assertEqual(contract["timeline"][1]["dependencies"], ["D12"])
        lane = contract["candidate_lanes"][1]
        self.assertEqual(lane["days"], ["D18", "D19", "D20"])
        self.assertEqual(lane["dependencies"], ["D12"])
        self.assertEqual(lane["validation_commands"], ["pytest"])

    def test_day_selector_filters_timeline(self) -> None:
        plan = self._plan_file(
            """# Timeline Plan

## Implementation Changes

- D01: add `src/a.py`.
- D02: add `src/b.py`.

## Success Criteria

- Both rows land.

## Validation

- pytest
"""
        )
        contract = MODULE.build_contract(plan, "/repo", "D02")
        self.assertEqual([row["label"] for row in contract["timeline"]], ["D02"])
        self.assertEqual(contract["mode"], "solo")
        self.assertEqual([lane["days"] for lane in contract["candidate_lanes"]], [["D02"]])
        self.assertEqual(contract["target_surfaces"], ["src/a.py", "src/b.py"])
        prompt = MODULE.render_prompts(contract)
        self.assertIn("- src/a.py", prompt)
        self.assertNotIn("D02", prompt)

    def test_overlapping_lanes_need_human(self) -> None:
        plan = self._plan_file(
            """# Overlap Plan

## Implementation Changes

- D01: update `src/app`.
- D02: update `src/app/routes.py`.

## Success Criteria

- Both rows land.

## Validation

- pytest
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(contract["mode"], "needs_human")
        self.assertTrue(
            any("overlapping lane" in item for item in contract["blocking_questions"])
        )

    def test_prompts_render_for_solo_and_needs_human(self) -> None:
        solo = {
            "mode": "solo",
            "work_item": "Small Change",
            "plan_source": "plan.md",
            "repo_root": "/repo",
            "success_criteria": ["Done"],
            "target_surfaces": ["src/app.py"],
            "off_limits": [],
            "validation_commands": ["pytest"],
            "human_gates": ["review gate"],
            "handoff_artifacts": ["handoff/swe-it/small-change.json"],
        }
        prompt = MODULE.render_prompts(solo)
        self.assertIn("swe-day(Small Change)", prompt)
        self.assertIn("review gate", prompt)
        self.assertIn("Final Clean-HEAD Verification", prompt)
        self.assertIn("temporary detached worktree", prompt)

        blocked = dict(solo)
        blocked["mode"] = "needs_human"
        blocked["blocking_questions"] = ["missing validation commands"]
        prompt = MODULE.render_prompts(blocked)
        self.assertIn("Execution dispatch is blocked.", prompt)

    def test_cli_contract_outputs_json(self) -> None:
        plan = self._plan_file(
            """# CLI Plan

## Implementation Changes

- Add `src/cli.py`.

## Success Criteria

- CLI works.

## Validation

- pytest
"""
        )
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "contract.json"
            code = MODULE.main(
                [
                    "contract",
                    "--plan",
                    plan,
                    "--repo",
                    "/repo",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["work_item"], "CLI Plan")
            self.assertIn("review_closeout", data)
            self.assertIn("ambiguity_policy", data)
            self.assertIn("final_verification", data)
            self.assertTrue(data["final_verification"]["clean_worktree_required"])
            self.assertTrue(
                data["final_verification"]["missing_file_detection_required"]
            )

    def test_contract_infers_required_lint_submodule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitmodules").write_text(
                """[submodule "vendor/lint"]
\tpath = vendor/lint
\turl = https://example.invalid/lint.git
""",
                encoding="utf-8",
            )
            plan = self._plan_file(
                """# Lint Plan

## Success Criteria

- Lint passes.

## Validation

- make lint
"""
            )

            contract = MODULE.build_contract(plan, str(root), None)

        self.assertEqual(
            contract["final_verification"]["required_submodules"],
            ["vendor/lint"],
        )

    def test_contract_does_not_infer_command_name_submodule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitmodules").write_text(
                """[submodule "tools/bazel"]
\tpath = tools/bazel
\turl = https://example.invalid/bazel.git
""",
                encoding="utf-8",
            )
            plan = self._plan_file(
                """# Bazel Plan

## Success Criteria

- Tests pass.

## Validation

- bazel test //...
"""
            )

            contract = MODULE.build_contract(plan, str(root), None)

        self.assertEqual(contract["final_verification"]["required_submodules"], [])

    def test_validation_extraction_skips_removed_pattern_examples(self) -> None:
        plan = self._plan_file(
            """# Pattern Scan Plan

## Success Criteria

- The migration is complete.

## Test Plan

- bazel test //...
- Search active authored surfaces for removed patterns:
  - .venv/bin/python
  - uv pip sync
  - python -m pytest
  - pip install -r
"""
        )

        contract = MODULE.build_contract(plan, "/repo", None)

        self.assertEqual(contract["validation_commands"], ["bazel test //..."])

    def test_validation_extraction_keeps_pattern_named_commands(self) -> None:
        plan = self._plan_file(
            """# Pattern Command Plan

## Success Criteria

- The migration is complete.

## Test Plan

- python -m pytest tests/test_removed_patterns.py
"""
        )

        contract = MODULE.build_contract(plan, "/repo", None)

        self.assertEqual(
            contract["validation_commands"],
            ["python -m pytest tests/test_removed_patterns.py"],
        )

    def test_validation_extraction_accepts_x_commands(self) -> None:
        plan = self._plan_file(
            """# Repository Wrapper Plan

## Success Criteria

- The repository checks pass.

## Validation

1. `x test //services/example/...`
2. `x check`
"""
        )

        contract = MODULE.build_contract(plan, "/repo", None)

        self.assertEqual(
            contract["validation_commands"],
            [
                "x test //services/example/...",
                "x check",
            ],
        )
        self.assertEqual(contract["mode"], "solo")

    def test_validation_extraction_keeps_pattern_intro_inline_command(self) -> None:
        plan = self._plan_file(
            """# Inline Pattern Command Plan

## Success Criteria

- The migration is complete.

## Test Plan

- Search for removed patterns with `python -m tools.scan_removed_patterns`
  - `python -m pytest`
"""
        )

        contract = MODULE.build_contract(plan, "/repo", None)

        self.assertEqual(
            contract["validation_commands"],
            ["python -m tools.scan_removed_patterns"],
        )

    def test_cli_contract_uses_latest_saved_plan_without_plan_arg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plans = root / "plans"
            plans.mkdir()
            node_modules = plans / "node_modules"
            node_modules.mkdir()
            ignored_plan = node_modules / "ignored.md"
            ignored_plan.write_text("# Ignored", encoding="utf-8")
            directory_named_md = plans / "not-a-file.md"
            directory_named_md.mkdir()
            older = plans / "older.plan.md"
            newer = plans / "newer.plan.md"
            older.write_text(
                """# Older

## Success Criteria

- Old done.

## Validation

- pytest
""",
                encoding="utf-8",
            )
            newer.write_text(
                """# Newer

## Success Criteria

- New done.

## Validation

- pytest
""",
                encoding="utf-8",
            )
            # Set the two modification times apart explicitly. Two files
            # written back to back can share one timestamp, and the
            # program then breaks the tie by path, which picks "older".
            os.utime(older, (1_700_000_000, 1_700_000_000))
            os.utime(newer, (1_700_000_100, 1_700_000_100))
            code = MODULE.main(
                [
                    "contract",
                    "--repo",
                    str(root),
                    "--out",
                    str(root / "out.json"),
                ]
            )
            self.assertEqual(code, 0)
            data = json.loads((root / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(data["work_item"], "Newer")
            self.assertEqual(data["plan_source"], str(newer))

    def test_latest_plan_ignores_non_plan_project_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / ".agents" / "projects" / "demo"
            project.mkdir(parents=True)
            readme = project / "PROJECT.md"
            plan = project / "plan.m2.gpt.md"
            plan.write_text(
                """# Project Plan

## Success Criteria

- Done.
""",
                encoding="utf-8",
            )
            readme.write_text("# Newer project note", encoding="utf-8")
            plan.touch()
            readme.touch()
            latest = MODULE._latest_saved_plan(str(root))
            self.assertEqual(latest, plan)

    def test_parsing_helpers_cover_edge_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            with self.assertRaises(SystemExit):
                MODULE._read_plan(str(directory_path))
            with self.assertRaises(SystemExit):
                MODULE._read_plan(None)
            with self.assertRaises(SystemExit):
                MODULE._read_plan(None, directory)
            self.assertTrue(MODULE._is_ignored_plan_path(Path("node_modules/a.md")))
        self.assertEqual(MODULE._read_plan("inline text").source, "<inline>")

        self.assertEqual(MODULE._strip_frontmatter(""), "")
        self.assertEqual(
            MODULE._strip_frontmatter("---\na: b\n---\n# Body"),
            "# Body",
        )
        self.assertEqual(MODULE._strip_frontmatter("---\na: b"), "---\na: b")

        titled = MODULE.PlanInput("plans/example.plan.md", "No heading")
        self.assertEqual(MODULE._title_from_plan(titled), "example.plan")
        inline = MODULE.PlanInput("<inline>", "No heading")
        self.assertEqual(MODULE._title_from_plan(inline), "approved-plan")

        self.assertEqual(MODULE._bullet_text("1. Numbered"), "Numbered")
        self.assertIsNone(MODULE._bullet_text("plain text"))

        self.assertTrue(MODULE._is_command("pytest"))
        self.assertFalse(MODULE._is_command("echo pytest"))

        self.assertFalse(MODULE._looks_like_path("https://example.com/a"))
        self.assertFalse(MODULE._looks_like_path("plain"))
        self.assertFalse(MODULE._looks_like_path("/"))

        self.assertEqual(
            MODULE._extract_paths_from_line("touch tools/cli.py and `src/app.py`."),
            ["tools/cli.py", "src/app.py"],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("see https://example.com/a"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("see http://localhost:3000/api"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("see https://user@example.com/a"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("clone ssh://git@github.com/org/repo"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("clone git@github.com:org/repo"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("clone git@example.com:org/repo"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line(
                "clone deploy@git.example.internal:team/repo"
            ),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("clone github.com/org/repo"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("clone gitlab.com/org/repo"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("clone bitbucket.org/org/repo"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("see www.example.com/path"),
            [],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("edit package.json/scripts/build"),
            ["package.json/scripts/build"],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("edit foo.test/bar.py"),
            ["foo.test/bar.py"],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("edit v1.api/routes.py"),
            ["v1.api/routes.py"],
        )
        self.assertEqual(
            MODULE._extract_paths_from_line("see `http://example.com/a`"),
            [],
        )
        self.assertEqual(MODULE._extract_paths_from_line("see `a/`"), [])
        self.assertEqual(MODULE._extract_paths_from_line("see a/"), [])
        spans = MODULE._url_spans("http://example.com/a and src/app.py")
        self.assertFalse(
            MODULE._inside_url("http://example.com/a and src/app.py", 25, spans)
        )
        self.assertTrue(MODULE._inside_url("see //src/app.py", 6, []))
        with mock.patch.object(MODULE, "_looks_like_path", return_value=False):
            self.assertEqual(MODULE._extract_paths_from_line("touch src/app.py"), [])

        self.assertEqual(MODULE._status_for_line("done and landed"), "done")
        self.assertEqual(MODULE._status_for_line("ready for review"), "in_review")
        self.assertEqual(MODULE._status_for_line("active WIP"), "in_progress")

        self.assertEqual(MODULE._labels_in_line("D03-D01"), ["D03", "D02", "D01"])
        self.assertEqual(MODULE._title_from_line("- D01", "D01"), "D01")
        self.assertEqual(MODULE._dedupe(["", "a", "a", " b "]), ["a", "b"])

        self.assertTrue(MODULE._paths_overlap("src/app", "src/app"))
        self.assertTrue(MODULE._paths_overlap("src/app/routes", "src/app"))
        self.assertTrue(MODULE._paths_overlap("src/app", "src/app/routes"))
        self.assertFalse(MODULE._paths_overlap("src/a", "src/b"))
        self.assertEqual(
            MODULE._extract_ambiguities({"implementation": ["- TBD: choose API"]}),
            ["TBD: choose API"],
        )

    def test_m2_plan_routes_to_durable_conductor(self) -> None:
        plan = self._plan_file(
            """# Durable Product Run

This run uses m2(plan_path, duration:4h, numM1s:3).

## Ambiguities

- Launch copy is unknown until product discovery.

## Success Criteria

- Acceptance matrix is green.
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(contract["mode"], "m2")
        self.assertIn("Launch copy is unknown", contract["ambiguities"][0])
        prompt = MODULE.render_prompts(contract)
        self.assertIn("m2(", prompt)
        self.assertIn("durable conductor loop", prompt)
        self.assertIn("code-review", prompt)
        self.assertIn("Final Clean-HEAD Verification", prompt)

    def test_m2_filename_suffix_and_overlap_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.m2.gpt.md"
            path.write_text("# Feature", encoding="utf-8")
            plan = MODULE.PlanInput(str(path), "# Feature")
            self.assertTrue(MODULE._is_m2_plan(plan))

            named = MODULE.PlanInput(
                str(Path(directory) / "feature.plan.m2.gpt.md"),
                "# Feature",
            )
            self.assertTrue(MODULE._is_m2_plan(named))

        left = {
            "label": "left",
            "target_surfaces": ["src/app"],
        }
        right = {
            "label": "right",
            "target_surfaces": ["src/app/routes.py"],
        }
        mode, blockers = MODULE._select_mode([], [], [left, right], [], True)
        self.assertEqual(mode, "needs_human")
        self.assertTrue(blockers)

    def test_contract_extracts_fences_gates_off_limits_and_missing_day(self) -> None:
        plan = self._plan_file(
            """---
name: gated
---
# Gated Plan

## Implementation Changes

- D01: add `src/a.py`.

## Success Criteria

- The row lands.

## Off Limits

- Do not edit `src/secret.py`.

## Validation

```bash
python3 -m unittest
```

- Also run `pytest`.
- Ignore `echo hi`.

## Human Gates

- Human gate required before execution.
- Approval from operator is needed.
- Run without approval when read-only.
## Human gate: Release manager approval before execution.
"""
        )
        contract = MODULE.build_contract(plan, "/repo", "D99")
        self.assertEqual(contract["mode"], "needs_human")
        self.assertIn("Do not edit src/secret.py.", contract["off_limits"])
        self.assertEqual(
            contract["validation_commands"],
            ["python3 -m unittest", "pytest"],
        )
        self.assertEqual(len(contract["human_gates"]), 3)
        self.assertIn(
            "Human gate: Release manager approval before execution.",
            contract["human_gates"],
        )
        self.assertEqual(
            MODULE._extract_human_gates(
                "## Operator-gated\n"
                "- Release approval required.\n"
                "## Required Approvals\n"
                "- Security approval required.\n"
                "## Human Gates ##\n"
                "## Approval ##\n"
                "## Release approval ##"
            ),
            [
                "Release approval required.",
                "Security approval required.",
                "Release approval",
            ],
        )
        self.assertIn(
            "requested D-day selector not found: D99",
            contract["blocking_questions"],
        )
        runnable_contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(runnable_contract["mode"], "solo")
        self.assertEqual(len(runnable_contract["human_gates"]), 3)

        duplicate_plan = self._plan_file(
            """# Duplicate Plan

## Implementation Changes

- D01 D01: add `src/a.py`.
- D01: repeat `src/b.py`.

## Success Criteria

- The row lands.

## Validation

- pytest
"""
        )
        duplicate_contract = MODULE.build_contract(duplicate_plan, "/repo", None)
        labels = [row["label"] for row in duplicate_contract["timeline"]]
        self.assertEqual(labels, ["D01"])

    def test_status_line_is_not_a_human_gate(self) -> None:
        plan = self._plan_file(
            """# Add a flag

Status: approved.

## Success Criteria

- The flag works.

## Validation

- make check

## Human Gates

- Approval from operator is needed.
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(
            contract["human_gates"], ["Approval from operator is needed."]
        )
        self.assertEqual(contract["mode"], "solo")
        self.assertEqual(
            MODULE._extract_human_gates(
                "Status: approved.\n"
                "- **Status:** awaiting approval\n"
                "status: approved\n"
                "## Status: approved\n"
                "- Human gate required before execution.\n"
            ),
            ["Human gate required before execution."],
        )
        self.assertEqual(
            MODULE._extract_human_gates(
                "1. Status: approved.\n"
                "2) **Status:** awaiting approval\n"
                "+ Status: approved\n"
                "- 3. Status: approved\n"
                "1. Approval from operator is needed.\n"
                "+ Human gate before deploy.\n"
            ),
            [
                "1. Approval from operator is needed.",
                "+ Human gate before deploy.",
            ],
        )

    def test_validation_heading_is_not_success_criteria(self) -> None:
        plan = self._plan_file(
            """# Add a flag

## Success Criteria

- The flag works.

## Validation

- `make check`
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(contract["success_criteria"], ["The flag works."])
        self.assertEqual(contract["validation_commands"], ["make check"])
        self.assertEqual(contract["mode"], "solo")

        validation_only = self._plan_file(
            """# Add a flag

## Validation

- make check
"""
        )
        contract = MODULE.build_contract(validation_only, "/repo", None)
        self.assertEqual(contract["success_criteria"], [])
        self.assertEqual(contract["validation_commands"], ["make check"])
        self.assertEqual(contract["mode"], "needs_human")
        self.assertEqual(
            contract["blocking_questions"],
            ["missing success or acceptance criteria"],
        )

    def test_off_limits_strips_backticks(self) -> None:
        plan = self._plan_file(
            """# Add a flag

## Off limits

- `Makefile`
- Do not edit `src/secret.py` or `docs/`.
"""
        )
        contract = MODULE.build_contract(plan, "/repo", None)
        self.assertEqual(
            contract["off_limits"],
            ["Makefile", "Do not edit src/secret.py or docs/."],
        )

    def test_selector_and_json_errors(self) -> None:
        with self.assertRaises(SystemExit):
            MODULE._normalize_day_selector("not-a-day")

        with self.assertRaises(SystemExit):
            MODULE._load_json_arg("[]")

    def test_low_level_contract_choices(self) -> None:
        empty_lane = {
            "label": "lane-d01",
            "target_surfaces": [],
        }
        mode, blockers = MODULE._select_mode(
            ["done"],
            ["pytest"],
            [empty_lane],
            [],
            False,
        )
        self.assertEqual(mode, "solo")
        self.assertEqual(blockers, [])

        mode, blockers = MODULE._select_mode(
            [],
            ["pytest"],
            [empty_lane],
            ["gate"],
            False,
        )
        self.assertEqual(mode, "needs_human")
        self.assertIn("missing success or acceptance criteria", blockers)

        mode, blockers = MODULE._select_mode(
            ["done"],
            ["pytest"],
            [empty_lane],
            ["gate"],
            False,
        )
        self.assertEqual(mode, "solo")
        self.assertEqual(blockers, [])

        mode, blockers = MODULE._select_mode([], [], [empty_lane], [], True)
        self.assertEqual(mode, "m2")
        self.assertEqual(blockers, [])

        self.assertFalse(MODULE._same_surfaces({}, {"target_surfaces": ["src/a"]}))
        self.assertFalse(MODULE._same_surfaces({"target_surfaces": ["src/a"]}, {}))
        self.assertEqual(MODULE._slug("!"), "plan")

    def test_render_multi_prompt_variants(self) -> None:
        contract = {
            "mode": "multi",
            "work_item": "Multi Plan",
            "plan_source": "plan.md",
            "repo_root": "/repo",
            "candidate_lanes": [
                {
                    "label": "lane-d01",
                    "title": "First",
                    "days": ["D01"],
                    "target_surfaces": ["src/a.py"],
                    "validation_commands": ["pytest"],
                    "dependencies": [],
                },
                {
                    "label": "lane-d02",
                    "title": "Second",
                    "days": ["D02"],
                    "target_surfaces": [],
                    "validation_commands": [],
                    "dependencies": [],
                },
            ],
            "off_limits": ["src/secret.py"],
            "validation_commands": ["pytest"],
            "human_gates": ["operator review"],
            "ambiguities": ["shared integration order"],
            "ambiguity_policy": ["record decisions"],
            "review_closeout": ["run code-review"],
        }
        prompt = MODULE.render_prompts(contract)
        self.assertIn("multi-swe-day(Multi Plan)", prompt)
        self.assertIn("operator review", prompt)
        self.assertIn("shared integration order", prompt)
        self.assertIn("run code-review", prompt)
        self.assertIn("Own: src/a.py", prompt)
        self.assertIn("Own: None stated.", prompt)
        self.assertIn("Off limits: src/secret.py", prompt)
        self.assertIn("Validate: use leader-provided validation.", prompt)
        self.assertIn("Final Clean-HEAD Verification", prompt)

        contract["off_limits"] = []
        prompt = MODULE.render_prompts(contract)
        self.assertIn("Off limits: None stated.", prompt)

    def test_render_next_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                MODULE.render_next(directory),
                "▶ swe-it READY · no active state found\n",
            )

            state_path = Path(directory) / "swe-it.json"
            state_path.write_text(
                json.dumps(
                    {
                        "mode": "needs_human",
                        "work_item": "Blocked",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.render_next(directory),
                "▶ swe-it BLOCKED · Blocked · human input required\n",
            )

            state_path.write_text(
                json.dumps(
                    {
                        "mode": "multi",
                        "work_item": "Parallel",
                        "candidate_lanes": [{}, {}],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.render_next(directory),
                "▶ swe-it READY · Parallel · dispatch 2 lanes\n",
            )

            state_path.write_text(
                json.dumps(
                    {
                        "mode": "solo",
                        "work_item": "Solo",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.render_next(directory),
                "▶ swe-it READY · Solo · dispatch solo swe-day\n",
            )

            state_path.write_text(
                json.dumps(
                    {
                        "mode": "m2",
                        "work_item": "Long",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.render_next(directory),
                "▶ swe-it READY · Long · dispatch m2 conductor\n",
            )

    def test_cli_subcommands_cover_stdout_and_output_files(self) -> None:
        contract = {
            "mode": "solo",
            "work_item": "CLI",
            "plan_source": "plan.md",
            "repo_root": "/repo",
            "success_criteria": ["Done"],
            "timeline": [{"label": "D01"}],
            "target_surfaces": ["src/a.py"],
            "off_limits": [],
            "candidate_lanes": [{"label": "lane-d01"}],
            "validation_commands": ["pytest"],
            "human_gates": [],
            "ambiguities": [],
            "ambiguity_policy": [],
            "review_closeout": [],
            "blocking_questions": [],
            "handoff_artifacts": ["handoff/swe-it/cli.json"],
        }
        with tempfile.TemporaryDirectory() as directory:
            contract_path = Path(directory) / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = MODULE.main(["timeline", "--contract", str(contract_path)])
            self.assertEqual(code, 0)
            self.assertIn("D01", stdout.getvalue())

            lanes_out = Path(directory) / "lanes.json"
            code = MODULE.main(
                ["lanes", "--contract", str(contract_path), "--out", str(lanes_out)]
            )
            self.assertEqual(code, 0)
            self.assertIn("lane-d01", lanes_out.read_text(encoding="utf-8"))

            prompts_out = Path(directory) / "prompts.md"
            code = MODULE.main(
                [
                    "prompts",
                    "--contract",
                    str(contract_path),
                    "--out",
                    str(prompts_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("swe-day(CLI)", prompts_out.read_text(encoding="utf-8"))

            nested = Path(directory) / "missing" / "dir"
            plan_path = Path(directory) / "plan.md"
            plan_path.write_text(
                "# Add a flag\n\n## Success Criteria\n\n- Done.\n\n"
                "## Validation\n\n- make check\n",
                encoding="utf-8",
            )
            code = MODULE.main(
                [
                    "contract",
                    "--plan",
                    str(plan_path),
                    "--repo",
                    directory,
                    "--out",
                    str(nested / "contract.json"),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn(
                '"mode": "solo"',
                (nested / "contract.json").read_text(encoding="utf-8"),
            )
            code = MODULE.main(
                [
                    "prompts",
                    "--contract",
                    str(contract_path),
                    "--out",
                    str(nested / "prompts" / "prompts.md"),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn(
                "swe-day(CLI)",
                (nested / "prompts" / "prompts.md").read_text(encoding="utf-8"),
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = MODULE.main(["prompts", "--contract", json.dumps(contract)])
            self.assertEqual(code, 0)
            self.assertIn("swe-day(CLI)", stdout.getvalue())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = MODULE.main(["next", "--state-dir", directory])
            self.assertEqual(code, 0)
            self.assertIn("no active state", stdout.getvalue())

    def test_verify_contract_runs_in_clean_head_worktree(self) -> None:
        root = self._git_repo()
        (root / "dirty-only.txt").write_text("not committed\n", encoding="utf-8")
        contract = {
            "repo_root": str(root),
            "final_verification": {
                "validation_commands": [
                    "test -f required.txt",
                    "test ! -f dirty-only.txt",
                ],
                "generated_artifact_checks": [],
            },
        }

        result = MODULE.verify_contract(contract)

        self.assertTrue(result["passed"], result)
        self.assertEqual(len(result["commands"]), 2)
        self.assertTrue(result["worktree_removed"])
        self.assertFalse(Path(result["worktree_path"]).exists())

    def test_verify_contract_initializes_submodules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            child = base / "child"
            child.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=str(child),
                check=True,
                capture_output=True,
            )
            (child / "child.txt").write_text("tracked\n", encoding="utf-8")
            self._commit_all(child, "Initial child commit")

            root = base / "parent"
            root.mkdir()
            subprocess.run(
                ["git", "init"],
                cwd=str(root),
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.file.allow=always",
                    "submodule",
                    "add",
                    str(child),
                    "deps/child",
                ],
                cwd=str(root),
                check=True,
                capture_output=True,
            )
            self._commit_all(root, "Add child submodule")

            contract = {
                "repo_root": str(root),
                "final_verification": {
                    "validation_commands": ["test -f deps/child/child.txt"],
                    "generated_artifact_checks": [],
                },
            }

            result = MODULE.verify_contract(contract)

            self.assertTrue(result["passed"], result)
            self.assertTrue(result["submodules_initialized"])
            self.assertEqual(result["required_submodules"], ["deps/child"])
            self.assertTrue(result["worktree_removed"])

    def test_verify_contract_reports_command_failure(self) -> None:
        root = self._git_repo()
        contract = {
            "repo_root": str(root),
            "final_verification": {
                "validation_commands": ["test -f missing.txt"],
                "generated_artifact_checks": [],
            },
        }

        result = MODULE.verify_contract(contract)

        self.assertFalse(result["passed"])
        self.assertEqual(result["commands"][0]["exit_code"], 1)
        self.assertIn("test -f missing.txt", result["failure_summaries"][0])
        self.assertTrue(result["worktree_removed"])

    def test_cli_verify_outputs_json_and_status(self) -> None:
        root = self._git_repo()
        contract = {
            "repo_root": str(root),
            "final_verification": {
                "validation_commands": ["test -f required.txt"],
                "generated_artifact_checks": [],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            contract_path = Path(directory) / "contract.json"
            output_path = Path(directory) / "verify.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            code = MODULE.main(
                [
                    "verify",
                    "--contract",
                    str(contract_path),
                    "--out",
                    str(output_path),
                ]
            )

            self.assertEqual(code, 0)
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(data["passed"])
            self.assertEqual(data["commands"][0]["command"], "test -f required.txt")

    def test_validation_whitespace_differs_by_form(self) -> None:
        head = "# Tabs\n\n## Success Criteria\n\n- Done.\n\n"
        bullet = self._plan_file(head + "## Validation\n\n- python3\t-c pass\n")
        contract = MODULE.build_contract(bullet, "/repo", None)
        self.assertEqual(contract["validation_commands"], ["python3 -c pass"])
        self.assertEqual(contract["mode"], "solo")

        fenced = self._plan_file(head + "## Notes\n\n```\npython3\t-c pass\n```\n")
        contract = MODULE.build_contract(fenced, "/repo", None)
        self.assertEqual(contract["validation_commands"], [])
        self.assertEqual(contract["mode"], "needs_human")

        inline = self._plan_file(head + "## Validation\n\nRun `python3\t-c pass`.\n")
        contract = MODULE.build_contract(inline, "/repo", None)
        self.assertEqual(contract["validation_commands"], [])

    def test_long_inline_text_is_not_read_as_a_path(self) -> None:
        text = "# Long\n\n" + "x" * 3000
        self.assertEqual(MODULE._read_plan(text).source, "<inline>")
        contract = json.dumps({"mode": "solo", "pad": "x" * 3000})
        self.assertEqual(MODULE._load_json_arg(contract)["mode"], "solo")

    def test_verify_contract_checks_out_the_recorded_commit(self) -> None:
        root = self._git_repo()
        real = MODULE._run_git
        state = {"advanced": False}

        def advancing(repo_root, args):
            result = real(repo_root, args)
            if args == ["rev-parse", "HEAD"] and not state["advanced"]:
                state["advanced"] = True
                (root / "later.txt").write_text("later\n", encoding="utf-8")
                self._commit_all(root, "Later commit")
            return result

        contract = {
            "repo_root": str(root),
            "final_verification": {
                "validation_commands": ["test ! -f later.txt"],
                "generated_artifact_checks": [],
            },
        }
        with mock.patch.object(MODULE, "_run_git", side_effect=advancing):
            result = MODULE.verify_contract(contract)

        self.assertTrue(state["advanced"])
        self.assertTrue(result["passed"], result)
        first = subprocess.run(
            ["git", "rev-parse", "HEAD~1"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(result["head"], first)

    def test_main_guard_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            argv = [
                str(SCRIPT_PATH),
                "next",
                "--state-dir",
                directory,
            ]
            stdout = io.StringIO()
            with mock.patch.object(sys, "argv", argv):
                with contextlib.redirect_stdout(stdout):
                    with self.assertRaises(SystemExit) as raised:
                        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
            self.assertEqual(raised.exception.code, 0)
            self.assertIn("swe-it READY", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
