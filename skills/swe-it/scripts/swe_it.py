#!/usr/bin/env python3
"""Build swe-it execution contracts, timelines, lanes, and prompts."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3
VERIFY_OUTPUT_TAIL_CHARS = 4000
COMMAND_PREFIXES = (
    "bazel",
    "make",
    "npm",
    "npx",
    "pnpm",
    "python",
    "python3",
    "pytest",
    "swift",
    "uv",
    "x",
    "xcodebuild",
)
PATH_RE = re.compile(
    r"`([^`\n]+[/][^`\n]+)`|" r"(?<![\w.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_./@:+-]+)"
)
URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s`<>)]+")
REMOTE_REF_RE = re.compile(
    r"(?<![\w@.-])(?:[A-Za-z0-9_.-]+@)?"
    r"(?:github\.com|gitlab\.com|bitbucket\.org)(?::|/)[^\s`<>)]+|"
    r"(?<![\w@.-])[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+:"
    r"[A-Za-z0-9_.-]+/[^\s`<>)]+|"
    r"(?<![\w@.-])www\.[A-Za-z0-9.-]+\.[A-Za-z]{2,}/[^\s`<>)]+"
)
STATUS_LINE_RE = re.compile(r"status\s*\**\s*:")
LIST_MARKER_RE = re.compile(r"^(?:[-*+]+\s*|\d+[.)]\s+)+")
D_LABEL_RE = re.compile(r"\bD(\d{1,3})\b", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
    r"\s+\d{1,2}(?:\s*[-/]\s*\d{1,2})?(?:,\s*\d{4})?\b|"
    r"\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
M2_PLAN_SUFFIXES = (
    ".plan.m2.gpt.md",
    "plan.m2.gpt.md",
    "/plan.m2.gpt.md",
)
M2_TEXT_HINTS = (
    "m2(",
    "manager-of-managers",
    "durable conductor",
    "numm1s:",
    "acceptance-first planning",
    "final response gate",
)


@dataclass
class PlanInput:
    source: str
    text: str


def _normalize_label(raw: str) -> str:
    value = int(raw)
    if value < 10:
        return f"D0{value}"
    return f"D{value}"


def _collapse(text: str) -> str:
    return " ".join(text.strip().split())


def _read_plan(plan_arg: str | None, repo_root: str | None = None) -> PlanInput:
    if plan_arg is None or not plan_arg.strip():
        if repo_root is None:
            raise SystemExit("plan argument is required")
        path = _latest_saved_plan(repo_root)
        return PlanInput(str(path), path.read_text(encoding="utf-8"))
    path = _existing_path(plan_arg)
    if path is not None:
        if path.is_file():
            return PlanInput(str(path), path.read_text(encoding="utf-8"))
        raise SystemExit(f"plan path is not a file: {path}")
    return PlanInput("<inline>", plan_arg)


def _existing_path(value: str) -> Path | None:
    try:
        path = Path(value).expanduser()
        if path.exists():
            return path
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def _latest_saved_plan(repo_root: str) -> Path:
    root = Path(repo_root).expanduser()
    search_roots = [
        root / "plans",
        root / ".agents" / "plans",
        root / ".agents" / "projects",
    ]
    candidates: list[Path] = []
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for path in search_root.rglob("*.md"):
            if not path.is_file():
                continue
            if _is_ignored_plan_path(path):
                continue
            if not _is_saved_plan_candidate(path, search_root):
                continue
            candidates.append(path)
    if not candidates:
        raise SystemExit("no saved plan found; pass --plan explicitly")
    return max(candidates, key=lambda path: (path.stat().st_mtime, str(path)))


def _is_ignored_plan_path(path: Path) -> bool:
    ignored_parts = {".git", "node_modules", "__pycache__"}
    for part in path.parts:
        if part in ignored_parts:
            return True
    return False


def _is_saved_plan_candidate(path: Path, search_root: Path) -> bool:
    if search_root.name != "projects":
        return True
    if "plan" in path.name.lower():
        return True
    return False


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    if lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def _title_from_plan(plan: PlanInput) -> str:
    for line in _strip_frontmatter(plan.text).splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return _collapse(stripped[2:])
    if plan.source != "<inline>":
        return Path(plan.source).stem
    return "approved-plan"


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for line in _strip_frontmatter(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            current = stripped.lstrip("#").strip().lower()
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return sections


def _bullet_text(line: str) -> str | None:
    stripped = line.strip()
    for marker in ("- ", "* "):
        if stripped.startswith(marker):
            return _collapse(stripped[len(marker) :])
    match = re.match(r"^\d+\.\s+(.*)$", stripped)
    if match:
        return _collapse(match.group(1))
    return None


def _extract_success_criteria(sections: dict[str, list[str]]) -> list[str]:
    criteria: list[str] = []
    names = ("success", "acceptance", "criteria", "test plan")
    for name, lines in sections.items():
        if not any(token in name for token in names):
            continue
        for line in lines:
            bullet = _bullet_text(line)
            if bullet:
                criteria.append(bullet)
    return _dedupe(criteria)


def _extract_off_limits(sections: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    names = ("off-limits", "off limits", "out of scope", "do not")
    for name, lines in sections.items():
        if not any(token in name for token in names):
            continue
        for line in lines:
            bullet = _bullet_text(line)
            if bullet:
                values.append(_collapse(bullet.replace("`", "")))
    return _dedupe(values)


def _is_command(text: str) -> bool:
    stripped = text.strip()
    for prefix in COMMAND_PREFIXES:
        if stripped == prefix:
            return True
        if stripped.startswith(prefix + " "):
            return True
    return False


def _extract_validation_commands(
    text: str, sections: dict[str, list[str]]
) -> list[str]:
    commands: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and _is_command(stripped):
            commands.append(stripped)
    for name, lines in sections.items():
        if "test" not in name and "validation" not in name and "verify" not in name:
            continue
        pattern_context_indent: int | None = None
        for line in lines:
            indent = len(line) - len(line.lstrip())
            stripped = line.strip()
            if pattern_context_indent is not None:
                if not stripped:
                    continue
                if indent > pattern_context_indent and _bullet_text(line):
                    continue
                pattern_context_indent = None
            bullet = _bullet_text(line)
            inline_commands = re.findall(r"`([^`\n]+)`", line)
            if bullet:
                if _is_command(bullet):
                    commands.append(bullet)
                elif _is_pattern_list_intro(bullet):
                    for inline in inline_commands:
                        if _is_command(inline):
                            commands.append(inline)
                    pattern_context_indent = indent
                    continue
            for inline in inline_commands:
                if _is_command(inline):
                    commands.append(inline)
    return _dedupe(commands)


def _is_pattern_list_intro(text: str) -> bool:
    lower = text.lower()
    if "pattern" not in lower:
        return False
    if "search" in lower:
        return True
    if "removed" in lower:
        return True
    return False


def _extract_paths_from_line(line: str) -> list[str]:
    paths: list[str] = []
    url_spans = _url_spans(line)
    for match in PATH_RE.finditer(line):
        value = match.group(1)
        start = match.start(1)
        if value is None:
            value = match.group(2)
            start = match.start(2)
        if _inside_url(line, start, url_spans):
            continue
        value = value.strip().strip(".,:;)")
        if _looks_like_path(value):
            paths.append(value)
    return _dedupe(paths)


def _url_spans(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in URL_RE.finditer(line):
        spans.append((match.start(), match.end()))
    for match in REMOTE_REF_RE.finditer(line):
        spans.append((match.start(), match.end()))
    return spans


def _inside_url(line: str, start: int, url_spans: list[tuple[int, int]]) -> bool:
    for span_start, span_end in url_spans:
        if span_start <= start and start < span_end:
            return True
    if start >= 2 and line[start - 2 : start] == "//":
        return True
    return False


def _looks_like_path(value: str) -> bool:
    blocked_prefixes = ("http://", "https://")
    for prefix in blocked_prefixes:
        if value.startswith(prefix):
            return False
    if "/" not in value:
        return False
    if len(value) < 3:
        return False
    return True


def _extract_target_surfaces(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        paths.extend(_extract_paths_from_line(line))
    return _dedupe(paths)


def _extract_human_gates(text: str) -> list[str]:
    gates: list[str] = []
    for line in text.splitlines():
        gate_text = _human_gate_candidate(line)
        if not gate_text:
            continue
        lower = gate_text.lower()
        if STATUS_LINE_RE.match(LIST_MARKER_RE.sub("", lower)):
            continue
        if "human gate" in lower or "operator-gated" in lower:
            gates.append(_collapse(gate_text))
        elif "approval" in lower or "approve" in lower:
            if "without approval" not in lower:
                gates.append(_collapse(gate_text))
    return _dedupe(gates)


def _extract_ambiguities(sections: dict[str, list[str]]) -> list[str]:
    values: list[str] = []
    names = (
        "ambigu",
        "open question",
        "blocking question",
        "decision",
        "unknown",
        "tbd",
        "risk",
    )
    for name, lines in sections.items():
        if any(token in name for token in names):
            for line in lines:
                bullet = _bullet_text(line)
                if bullet:
                    values.append(bullet)
            continue
        for line in lines:
            lower = line.lower()
            if "tbd" in lower or "unclear" in lower or "unknown" in lower:
                values.append(_collapse(line.strip("- *")))
    return _dedupe(values)


def _human_gate_candidate(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("#"):
        heading = stripped.strip("#").strip()
        generic = heading.rstrip(":").lower()
        generic_headings = (
            "human gate",
            "human gates",
            "operator gate",
            "operator gates",
            "operator-gated",
            "operator gated",
            "approvals",
            "approval",
            "required approvals",
            "required approval",
            "human approvals",
            "human approval",
            "operator approvals",
            "operator approval",
        )
        if generic in generic_headings:
            return ""
        return heading
    return stripped.strip("- *")


def _status_for_line(line: str) -> str:
    lower = line.lower()
    if "done" in lower or "complete" in lower or "landed" in lower:
        return "done"
    if "review" in lower:
        return "in_review"
    if "active" in lower or "in progress" in lower or "wip" in lower:
        return "in_progress"
    return "planned"


def _calendar_window(line: str) -> str:
    matches = DATE_RE.findall(line)
    if not matches:
        return ""
    return ", ".join(_collapse(match) for match in matches)


def _labels_in_line(line: str) -> list[str]:
    labels: list[str] = []
    range_re = re.compile(
        r"\bD(\d{1,3})\s*(?:-|–|—)\s*D?(\d{1,3})\b",
        re.IGNORECASE,
    )
    for match in range_re.finditer(line):
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= end:
            values = range(start, end + 1)
        else:
            values = range(start, end - 1, -1)
        for value in values:
            labels.append(_normalize_label(str(value)))
    for match in D_LABEL_RE.finditer(line):
        labels.append(_normalize_label(match.group(1)))
    return _dedupe(labels)


def _implementation_bullets(sections: dict[str, list[str]]) -> list[str]:
    bullets: list[str] = []
    keywords = (
        "implementation",
        "key changes",
        "behavior",
        "changes",
        "public interface",
    )
    for name, lines in sections.items():
        if not any(keyword in name for keyword in keywords):
            continue
        for line in lines:
            bullet = _bullet_text(line)
            if bullet:
                bullets.append(bullet)
    return _dedupe(bullets)


def _derive_timeline(
    text: str,
    sections: dict[str, list[str]],
    success_criteria: list[str],
    validation_commands: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous = ""
    for line in text.splitlines():
        labels = _labels_in_line(line)
        if not labels:
            continue
        for label in labels:
            if label in seen:
                continue
            dependencies: list[str] = []
            if previous:
                dependencies.append(previous)
            row = {
                "label": label,
                "title": _title_from_line(line, label),
                "dependencies": dependencies,
                "target_surfaces": _extract_paths_from_line(line),
                "success_criteria": success_criteria,
                "validation_commands": validation_commands,
                "status": _status_for_line(line),
                "calendar_window": _calendar_window(line),
            }
            rows.append(row)
            seen.add(label)
            previous = label
    if rows:
        return rows
    bullets = _implementation_bullets(sections)
    for index, bullet in enumerate(bullets, start=1):
        label = _normalize_label(str(index))
        dependencies = []
        if rows:
            dependencies = [rows[-1]["label"]]
        row = {
            "label": label,
            "title": bullet,
            "dependencies": dependencies,
            "target_surfaces": _extract_paths_from_line(bullet),
            "success_criteria": success_criteria,
            "validation_commands": validation_commands,
            "status": "planned",
            "calendar_window": "",
        }
        rows.append(row)
    return rows


def _title_from_line(line: str, label: str) -> str:
    title = _collapse(line)
    title = re.sub(r"^[|>\-\*\s]+", "", title)
    title = title.replace(label, "").strip(" -|:;")
    if not title:
        return label
    return title


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _collapse(value)
        if not clean:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _paths_overlap(left: str, right: str) -> bool:
    left_clean = left.strip("/")
    right_clean = right.strip("/")
    if left_clean == right_clean:
        return True
    if left_clean.startswith(right_clean + "/"):
        return True
    if right_clean.startswith(left_clean + "/"):
        return True
    return False


def _row_lane(row: dict[str, Any]) -> dict[str, Any]:
    label = row["label"]
    return {
        "label": f"lane-{label.lower()}",
        "title": row["title"],
        "days": [label],
        "target_surfaces": list(row.get("target_surfaces", [])),
        "validation_commands": list(row.get("validation_commands", [])),
        "dependencies": list(row.get("dependencies", [])),
    }


def _same_surfaces(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_surfaces = left.get("target_surfaces", [])
    right_surfaces = right.get("target_surfaces", [])
    if not left_surfaces:
        return False
    if not right_surfaces:
        return False
    return left_surfaces == right_surfaces


def _extend_lane(lane: dict[str, Any], row: dict[str, Any]) -> None:
    lane["days"].append(row["label"])
    lane["label"] = f"lane-{lane['days'][0].lower()}-{lane['days'][-1].lower()}"
    dependencies = lane.get("dependencies", [])
    dependencies.extend(row.get("dependencies", []))
    lane["dependencies"] = [
        label for label in _dedupe(dependencies) if label not in lane["days"]
    ]
    validation = lane.get("validation_commands", [])
    validation.extend(row.get("validation_commands", []))
    lane["validation_commands"] = _dedupe(validation)


def _candidate_lanes(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lanes: list[dict[str, Any]] = []
    previous_row: dict[str, Any] | None = None
    for row in timeline:
        if lanes and previous_row is not None and _same_surfaces(previous_row, row):
            _extend_lane(lanes[-1], row)
        else:
            lanes.append(_row_lane(row))
        previous_row = row
    return lanes


def _overlap_messages(lanes: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for left_index, left in enumerate(lanes):
        for right in lanes[left_index + 1 :]:
            for left_path in left.get("target_surfaces", []):
                for right_path in right.get("target_surfaces", []):
                    if _paths_overlap(left_path, right_path):
                        messages.append(
                            "overlapping lane target surfaces: "
                            f"{left['label']}:{left_path} and "
                            f"{right['label']}:{right_path}"
                        )
    return _dedupe(messages)


def _select_mode(
    success_criteria: list[str],
    validation_commands: list[str],
    lanes: list[dict[str, Any]],
    human_gates: list[str],
    m2_plan: bool,
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if m2_plan:
        blockers.extend(_overlap_messages(lanes))
        if blockers:
            return ("needs_human", blockers)
        return ("m2", blockers)
    if not success_criteria:
        blockers.append("missing success or acceptance criteria")
    if not validation_commands:
        blockers.append("missing validation commands")
    blockers.extend(_overlap_messages(lanes))
    if blockers:
        return ("needs_human", blockers)
    lanes_with_surfaces = []
    for lane in lanes:
        if lane.get("target_surfaces"):
            lanes_with_surfaces.append(lane)
    if len(lanes) >= 2 and len(lanes_with_surfaces) == len(lanes):
        return ("multi", blockers)
    return ("solo", blockers)


def _is_m2_plan(plan: PlanInput) -> bool:
    source = plan.source.lower()
    for suffix in M2_PLAN_SUFFIXES:
        if source.endswith(suffix):
            return True
    text = plan.text.lower()
    for hint in M2_TEXT_HINTS:
        if hint in text:
            return True
    return False


def _submodule_paths(repo_root: str) -> list[str]:
    root = Path(repo_root).expanduser()
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return []
    process = subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(gitmodules),
            "--get-regexp",
            r"submodule\..*\.path",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        return []
    paths: list[str] = []
    for line in process.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            paths.append(parts[1])
    return _dedupe(paths)


def _command_tokens(command: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_.-]+", command.lower()))


def _required_submodules(
    validation_commands: list[str],
    repo_root: str,
) -> list[str]:
    paths = _submodule_paths(repo_root)
    if not paths:
        return []
    tokens: set[str] = set()
    for command in validation_commands:
        tokens.update(_command_tokens(command))
    required: list[str] = []
    ignored_leaf_tokens = set(COMMAND_PREFIXES)
    ignored_leaf_tokens.add("git")
    for path in paths:
        leaf = Path(path).name.lower()
        if leaf in ignored_leaf_tokens:
            continue
        if leaf in tokens:
            required.append(path)
    return _dedupe(required)


def _final_verification(
    validation_commands: list[str],
    required_submodules: list[str] | None = None,
) -> dict[str, Any]:
    if required_submodules is None:
        required_submodules = []
    return {
        "clean_worktree_required": True,
        "missing_file_detection_required": True,
        "validation_commands": validation_commands,
        "generated_artifact_checks": [],
        "required_submodules": required_submodules,
        "instructions": [
            "After all implementation commits and review-addressing commits land, "
            "validate committed HEAD from a temporary detached clean worktree.",
            "Do not treat validation in a dirty working checkout as sufficient for "
            "final response.",
            "If clean-HEAD validation fails because a source, generated artifact, "
            "or dependency input is missing, commit the missing file or update the "
            "contracted artifact, then rerun clean-HEAD verification.",
        ],
    }


def build_contract(
    plan_arg: str | None,
    repo_root: str,
    day: str | None,
) -> dict[str, Any]:
    plan = _read_plan(plan_arg, repo_root)
    sections = _sections(plan.text)
    success_criteria = _extract_success_criteria(sections)
    validation_commands = _extract_validation_commands(plan.text, sections)
    timeline = _derive_timeline(
        plan.text,
        sections,
        success_criteria,
        validation_commands,
    )
    if day:
        selected_label = _normalize_day_selector(day)
        timeline = [row for row in timeline if row["label"] == selected_label]
    target_surfaces = _extract_target_surfaces(plan.text)
    off_limits = _extract_off_limits(sections)
    human_gates = _extract_human_gates(plan.text)
    ambiguities = _extract_ambiguities(sections)
    lanes = _candidate_lanes(timeline)
    m2_plan = _is_m2_plan(plan)
    required_submodules = _required_submodules(validation_commands, repo_root)
    mode, blockers = _select_mode(
        success_criteria,
        validation_commands,
        lanes,
        human_gates,
        m2_plan,
    )
    if day and not timeline:
        mode = "needs_human"
        blockers.append(f"requested D-day selector not found: {day}")
    work_item = _title_from_plan(plan)
    contract = {
        "schema_version": SCHEMA_VERSION,
        "plan_source": plan.source,
        "repo_root": repo_root,
        "mode": mode,
        "work_item": work_item,
        "success_criteria": success_criteria,
        "timeline": timeline,
        "target_surfaces": target_surfaces,
        "off_limits": off_limits,
        "candidate_lanes": lanes,
        "validation_commands": validation_commands,
        "human_gates": human_gates,
        "ambiguities": ambiguities,
        "ambiguity_policy": [
            "Resolve implementation ambiguity by repo discovery, tests, and "
            "small reversible choices before asking.",
            "Pause only for high-impact intent, destructive scope, "
            "security/privacy boundary, missing acceptance, missing validation, "
            "or an explicit human-review gate.",
            "Record every material ambiguity decision in the downstream "
            "handoff or m2 event log.",
        ],
        "review_closeout": [
            "Run code-review over the final diff unless the run made no "
            "code, doc, config, plan, or generated-output changes.",
            "Run address-comments until TODO(agent), AGENT:, and "
            "TODO(code-review:<id>) markers are resolved or blocked with owner, "
            "reason, and next action.",
            "Apply the l8 risk order to final review; for multi-lane, protocol, "
            "or long-running routes, include an l8 auditor pass.",
            "Use ask-human-review style review surfaces for human-review gates; "
            "do not advance behind an unmet human gate.",
        ],
        "final_verification": _final_verification(
            validation_commands,
            required_submodules,
        ),
        "blocking_questions": _dedupe(blockers),
        "handoff_artifacts": [
            f"handoff/swe-it/{_slug(work_item)}.json",
        ],
    }
    return contract


def _normalize_day_selector(day: str) -> str:
    match = D_LABEL_RE.search(day)
    if not match:
        raise SystemExit(f"invalid D-day selector: {day}")
    return _normalize_label(match.group(1))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        return "plan"
    return slug


def _load_json_arg(value: str) -> dict[str, Any]:
    path = _existing_path(value)
    if path is not None:
        text = path.read_text(encoding="utf-8")
    else:
        text = value
    data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("contract JSON must be an object")
    return data


def _write_text(out_path: str, text: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_or_print(data: Any, out_path: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if out_path:
        _write_text(out_path, text)
    else:
        sys.stdout.write(text)


def render_prompts(contract: dict[str, Any]) -> str:
    mode = contract.get("mode")
    if mode == "m2":
        return _render_m2_prompt(contract)
    if mode == "multi":
        return _render_multi_prompt(contract)
    if mode == "solo":
        return _render_solo_prompt(contract)
    return _render_needs_human_prompt(contract)


def _render_list(title: str, values: list[Any]) -> list[str]:
    lines = [f"## {title}"]
    if not values:
        lines.append("- None stated.")
        return lines
    for value in values:
        lines.append(f"- {value}")
    return lines


def _render_solo_prompt(contract: dict[str, Any]) -> str:
    lines = [
        f"# swe-day dispatch: {contract['work_item']}",
        "",
        f"Invoke: `swe-day({contract['work_item']})`",
        "",
        f"Plan source: `{contract['plan_source']}`",
        f"Repo root: `{contract['repo_root']}`",
        "",
    ]
    lines.extend(_render_list("Success Criteria", contract["success_criteria"]))
    lines.append("")
    lines.extend(_render_list("Target Surfaces", contract["target_surfaces"]))
    lines.append("")
    lines.extend(_render_list("Off Limits", contract["off_limits"]))
    lines.append("")
    lines.extend(_render_list("Validation", contract["validation_commands"]))
    lines.append("")
    lines.extend(_render_list("Human Gates", contract.get("human_gates", [])))
    lines.append("")
    lines.extend(_render_list("Ambiguities", contract.get("ambiguities", [])))
    lines.append("")
    lines.extend(
        _render_list("Ambiguity Policy", contract.get("ambiguity_policy", []))
    )
    lines.append("")
    lines.extend(_render_list("Review Closeout", contract.get("review_closeout", [])))
    lines.append("")
    lines.extend(_render_final_verification(contract))
    lines.append("")
    lines.extend(_render_list("Handoff Artifacts", contract["handoff_artifacts"]))
    return "\n".join(lines).rstrip() + "\n"


def _render_m2_prompt(contract: dict[str, Any]) -> str:
    lines = [
        f"# m2 dispatch: {contract['work_item']}",
        "",
        f"Invoke: `m2({contract['plan_source']})`",
        "",
        f"Plan source: `{contract['plan_source']}`",
        f"Repo root: `{contract['repo_root']}`",
        "",
        "## Execution Contract",
        "- Treat this as execution, not planning or summary.",
        "- Run the m2 durable conductor loop until terminal state, explicit "
        "human stop, true blocker, or final-response gate permission.",
        "- Use m2 acceptance-first planning before dispatch.",
        "- Fan out through m2 managers and lower-level swe-day or "
        "multi-swe-day lanes whenever safe disjoint work exists.",
        "- Delivery events, PRs, green validation, and queued CI are "
        "checkpoints, not stop conditions.",
        "",
    ]
    lines.extend(_render_list("Success Criteria", contract["success_criteria"]))
    lines.append("")
    lines.extend(_render_list("Target Surfaces", contract["target_surfaces"]))
    lines.append("")
    lines.extend(_render_list("Off Limits", contract["off_limits"]))
    lines.append("")
    lines.extend(_render_list("Validation", contract["validation_commands"]))
    lines.append("")
    lines.extend(_render_list("Human Gates", contract.get("human_gates", [])))
    lines.append("")
    lines.extend(_render_list("Ambiguities", contract.get("ambiguities", [])))
    lines.append("")
    lines.extend(
        _render_list("Ambiguity Policy", contract.get("ambiguity_policy", []))
    )
    lines.append("")
    lines.extend(_render_list("Review Closeout", contract.get("review_closeout", [])))
    lines.append("")
    lines.extend(_render_final_verification(contract))
    lines.append("")
    lines.extend(_render_list("Handoff Artifacts", contract["handoff_artifacts"]))
    return "\n".join(lines).rstrip() + "\n"


def _render_multi_prompt(contract: dict[str, Any]) -> str:
    lines = [
        f"# multi-swe-day dispatch: {contract['work_item']}",
        "",
        f"Invoke: `multi-swe-day({contract['work_item']})`",
        "",
        f"Plan source: `{contract['plan_source']}`",
        f"Repo root: `{contract['repo_root']}`",
        "",
        "## Leader Prompt",
        "- Hold the single-writer lock.",
        "- Register only the lanes listed below.",
        "- Own shared joins, final validation, reconcile, and gates.",
        "",
    ]
    lines.extend(_render_list("Human Gates", contract.get("human_gates", [])))
    lines.append("")
    lines.extend(_render_list("Ambiguities", contract.get("ambiguities", [])))
    lines.append("")
    lines.extend(
        _render_list("Ambiguity Policy", contract.get("ambiguity_policy", []))
    )
    lines.append("")
    for lane in contract["candidate_lanes"]:
        lines.append(f"## Builder Prompt: {lane['label']}")
        lines.append(f"- Title: {lane['title']}")
        lines.append(f"- D rows: {', '.join(lane['days'])}")
        surfaces = lane.get("target_surfaces", [])
        if surfaces:
            lines.append(f"- Own: {', '.join(surfaces)}")
        else:
            lines.append("- Own: None stated.")
        off_limits = contract.get("off_limits", [])
        if off_limits:
            lines.append(f"- Off limits: {', '.join(off_limits)}")
        else:
            lines.append("- Off limits: None stated.")
        validation = lane.get("validation_commands", [])
        if validation:
            lines.append(f"- Validate: {' && '.join(validation)}")
        else:
            lines.append("- Validate: use leader-provided validation.")
        lines.append("- Report commit, validation output, and residual risks.")
        lines.append("")
    lines.extend(_render_list("Final Validation", contract["validation_commands"]))
    lines.append("")
    lines.extend(_render_list("Review Closeout", contract.get("review_closeout", [])))
    lines.append("")
    lines.extend(_render_final_verification(contract))
    return "\n".join(lines).rstrip() + "\n"


def _render_final_verification(contract: dict[str, Any]) -> list[str]:
    verification = contract.get("final_verification")
    if not isinstance(verification, dict):
        verification = _final_verification(contract.get("validation_commands", []))
    lines = ["## Final Clean-HEAD Verification"]
    lines.append("- Run after implementation, review, and address-comments commits land.")
    lines.append(
        "- Use a temporary detached worktree at committed HEAD; do not rely on "
        "the dirty working checkout."
    )
    if verification.get("missing_file_detection_required"):
        lines.append(
            "- Treat clean-worktree build/test failures from missing files or "
            "generated artifacts as implementation failures to fix and recommit."
        )
    commands = _string_list(
        verification.get("validation_commands", contract.get("validation_commands", []))
    )
    generated_checks = _string_list(verification.get("generated_artifact_checks", []))
    all_commands = commands + generated_checks
    required_submodules = _string_list(verification.get("required_submodules", []))
    for path in required_submodules:
        lines.append("- Initialize submodule: `" + path + "`")
    if all_commands:
        for command in all_commands:
            lines.append("- Verify: `" + command + "`")
    else:
        lines.append("- Verify: no commands stated in the contract.")
    return lines


def _render_needs_human_prompt(contract: dict[str, Any]) -> str:
    lines = [
        f"# swe-it needs human input: {contract['work_item']}",
        "",
        "Execution dispatch is blocked.",
        "",
    ]
    lines.extend(_render_list("Blocking Questions", contract["blocking_questions"]))
    return "\n".join(lines).rstrip() + "\n"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            clean = _collapse(item)
            if clean:
                result.append(clean)
    return result


def _command_specs(contract: dict[str, Any]) -> list[dict[str, str]]:
    verification = contract.get("final_verification")
    if not isinstance(verification, dict):
        verification = _final_verification(contract.get("validation_commands", []))
    specs: list[dict[str, str]] = []
    for command in _string_list(
        verification.get("validation_commands", contract.get("validation_commands", []))
    ):
        specs.append({"source": "validation", "command": command})
    for command in _string_list(verification.get("generated_artifact_checks", [])):
        specs.append({"source": "generated_artifact_check", "command": command})
    return specs


def _tail(value: str) -> str:
    if len(value) <= VERIFY_OUTPUT_TAIL_CHARS:
        return value
    return value[-VERIFY_OUTPUT_TAIL_CHARS:]


def _process_summary(process: subprocess.CompletedProcess[str]) -> str:
    stderr = _collapse(process.stderr)
    stdout = _collapse(process.stdout)
    if stderr:
        return stderr
    if stdout:
        return stdout
    return "exit " + str(process.returncode)


def _run_git(
    repo_root: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def _run_verify_command(
    command: str,
    source: str,
    worktree_path: Path,
) -> dict[str, Any]:
    process = subprocess.run(
        command,
        cwd=str(worktree_path),
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
    )
    passed = process.returncode == 0
    return {
        "source": source,
        "command": command,
        "exit_code": process.returncode,
        "passed": passed,
        "stdout_tail": _tail(process.stdout),
        "stderr_tail": _tail(process.stderr),
        "summary": _process_summary(process),
    }


def _init_submodules(
    worktree_path: Path,
    submodule_paths: list[str],
) -> subprocess.CompletedProcess[str] | None:
    if not submodule_paths:
        return None
    if not (worktree_path / ".gitmodules").exists():
        return None
    return _run_git(
        worktree_path,
        [
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--",
            *submodule_paths,
        ],
    )


def verify_contract(contract: dict[str, Any]) -> dict[str, Any]:
    repo_value = contract.get("repo_root")
    if not isinstance(repo_value, str):
        repo_value = "."
    repo_root = Path(repo_value).expanduser().resolve()
    temp_parent = Path(tempfile.mkdtemp(prefix="swe-it-verify-"))
    worktree_path = temp_parent / "head"
    result: dict[str, Any] = {
        "passed": False,
        "repo_root": str(repo_root),
        "head": "",
        "worktree_path": str(worktree_path),
        "worktree_removed": False,
        "commands": [],
        "failure_summaries": [],
        "submodules_initialized": False,
        "required_submodules": [],
        "setup_error": "",
        "cleanup_error": "",
    }
    try:
        rev_parse = _run_git(repo_root, ["rev-parse", "HEAD"])
        if rev_parse.returncode != 0:
            result["setup_error"] = _process_summary(rev_parse)
            result["failure_summaries"] = [result["setup_error"]]
            return result
        result["head"] = _collapse(rev_parse.stdout)

        add = _run_git(
            repo_root,
            ["worktree", "add", "--detach", str(worktree_path), result["head"]],
        )
        if add.returncode != 0:
            result["setup_error"] = _process_summary(add)
            result["failure_summaries"] = [result["setup_error"]]
            return result
        checked_out = _run_git(worktree_path, ["rev-parse", "HEAD"])
        if _collapse(checked_out.stdout) != result["head"]:
            result["setup_error"] = "worktree is not at " + result["head"]
            result["failure_summaries"] = [result["setup_error"]]
            return result

        verification = contract.get("final_verification")
        if not isinstance(verification, dict):
            verification = {}
        required_submodules = _string_list(
            verification.get(
                "required_submodules",
                contract.get("required_submodules", []),
            )
        )
        if not required_submodules:
            commands = [spec["command"] for spec in _command_specs(contract)]
            required_submodules = _required_submodules(commands, str(repo_root))
        result["required_submodules"] = required_submodules
        submodules = _init_submodules(worktree_path, required_submodules)
        if submodules is not None:
            result["submodules_initialized"] = True
            if submodules.returncode != 0:
                result["setup_error"] = _process_summary(submodules)
                result["failure_summaries"] = [result["setup_error"]]
                return result

        failures: list[str] = []
        for spec in _command_specs(contract):
            command_result = _run_verify_command(
                spec["command"],
                spec["source"],
                worktree_path,
            )
            result["commands"].append(command_result)
            if not command_result["passed"]:
                failures.append(spec["command"] + ": " + command_result["summary"])
        result["failure_summaries"] = failures
        result["passed"] = not failures
        return result
    finally:
        if worktree_path.exists():
            remove = _run_git(
                repo_root,
                ["worktree", "remove", "--force", str(worktree_path)],
            )
            if remove.returncode == 0:
                result["worktree_removed"] = True
            else:
                result["cleanup_error"] = _process_summary(remove)
                result["passed"] = False
        else:
            result["worktree_removed"] = True
        shutil.rmtree(temp_parent, ignore_errors=True)


def render_next(state_dir: str) -> str:
    state_path = Path(state_dir).expanduser() / "swe-it.json"
    if not state_path.exists():
        return "▶ swe-it READY · no active state found\n"
    contract = _load_json_arg(str(state_path))
    mode = contract.get("mode", "needs_human")
    work_item = contract.get("work_item", "unknown")
    if mode == "needs_human":
        return f"▶ swe-it BLOCKED · {work_item} · human input required\n"
    if mode == "multi":
        lanes = contract.get("candidate_lanes", [])
        return f"▶ swe-it READY · {work_item} · dispatch {len(lanes)} lanes\n"
    if mode == "m2":
        return f"▶ swe-it READY · {work_item} · dispatch m2 conductor\n"
    return f"▶ swe-it READY · {work_item} · dispatch solo swe-day\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build swe-it execution contracts and prompts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    contract = subparsers.add_parser("contract")
    contract.add_argument("--plan")
    contract.add_argument("--repo", required=True)
    contract.add_argument("--day")
    contract.add_argument("--out")

    timeline = subparsers.add_parser("timeline")
    timeline.add_argument("--contract", required=True)
    timeline.add_argument("--out")

    lanes = subparsers.add_parser("lanes")
    lanes.add_argument("--contract", required=True)
    lanes.add_argument("--out")

    prompts = subparsers.add_parser("prompts")
    prompts.add_argument("--contract", required=True)
    prompts.add_argument("--out")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--contract", required=True)
    verify.add_argument("--out")

    next_cmd = subparsers.add_parser("next")
    next_cmd.add_argument("--state-dir", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "contract":
        contract = build_contract(args.plan, args.repo, args.day)
        _write_or_print(contract, args.out)
        return 0
    if args.command == "timeline":
        contract = _load_json_arg(args.contract)
        _write_or_print(contract.get("timeline", []), args.out)
        return 0
    if args.command == "lanes":
        contract = _load_json_arg(args.contract)
        _write_or_print(contract.get("candidate_lanes", []), args.out)
        return 0
    if args.command == "prompts":
        contract = _load_json_arg(args.contract)
        text = render_prompts(contract)
        if args.out:
            _write_text(args.out, text)
        else:
            sys.stdout.write(text)
        return 0
    if args.command == "verify":
        contract = _load_json_arg(args.contract)
        result = verify_contract(contract)
        _write_or_print(result, args.out)
        if result.get("passed"):
            return 0
        return 1
    sys.stdout.write(render_next(args.state_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
