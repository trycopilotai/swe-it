#!/usr/bin/env python3
"""Render an agent's raw event stream as a readable transcript.

    python3 scripts/render_invocation.py --client claude-code \\
        --raw run.jsonl --prompt prompt.txt \\
        --capture-root <fixture> --plugin-root <plugin-dir> \\
        --home <home> --hostname <host> \\
        --out evidence/transcripts/<date>-claude-code-invocation.txt

``--client`` is ``claude-code`` (``claude --print --output-format
stream-json --verbose``) or ``codex`` (``codex exec --json``). The
transcript holds the prompt, every tool call with its name and
arguments, each call's status where the stream records one, and the
agent's final message verbatim. Tool output is left out.

Five replacements are the only edits. They run on the raw stream and
the prompt before rendering, in this order:

1. ``replace-plugin-root``: each ``--plugin-root`` path (the directory
   the client loaded the skill from) becomes ``/plugin``.
2. ``replace-scratch-root``: the client's own scratch directory, a
   ``/private/tmp/claude-<uid>/<slug>`` prefix with its slug, becomes
   ``/scratch``.
3. ``replace-capture-root``: the fixture's absolute path becomes
   ``/work``.
4. ``replace-home``: the home directory becomes ``~``.
5. ``replace-hostname``: the hostname becomes ``host``.

A path is replaced only as a whole prefix: the next character must not
continue the same path segment. A tool call's arguments are then cut
to ``LIMIT`` characters, the same rule for every call. The output
depends only on the inputs.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

LIMIT = 400
SEGMENT = r"(?![A-Za-z0-9._-])"
SCRATCH = re.compile(r"(?:/private)?/tmp/claude-[0-9]+/[A-Za-z0-9._-]+" + SEGMENT)


def _cut(text: str) -> str:
    if len(text) <= LIMIT:
        return text
    return text[:LIMIT] + " [... %d more characters]" % (len(text) - LIMIT)


def claude_code(events: list) -> tuple:
    header, calls, final = {}, [], ""
    status = {}
    for event in events:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            header["model"] = event.get("model", "")
            header["version"] = event.get("claude_code_version", "")
        elif kind == "assistant":
            for part in event["message"].get("content", []):
                if part.get("type") == "tool_use":
                    calls.append((part["id"], part["name"], part["input"]))
        elif kind == "user":
            content = event["message"].get("content")
            for part in content if isinstance(content, list) else []:
                if part.get("type") == "tool_result":
                    failed = part.get("is_error") is True
                    status[part["tool_use_id"]] = "error" if failed else "ok"
        elif kind == "result":
            final = event.get("result", "")
            header["result"] = event.get("subtype", "")
    lines = [
        (
            name,
            json.dumps(arguments, ensure_ascii=False, sort_keys=True),
            status.get(call_id, "unknown"),
        )
        for call_id, name, arguments in calls
    ]
    return header, lines, final


def codex(events: list) -> tuple:
    header, lines, final = {}, [], ""
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event["item"]
        kind = item.get("type")
        if kind == "command_execution":
            code = item.get("exit_code")
            state = "unknown" if code is None else "exit %d" % code
            lines.append(("command_execution", item.get("command", ""), state))
        elif kind == "agent_message":
            final = item.get("text", "")
        elif kind in ("reasoning", "todo_list"):
            continue
        else:
            body = {key: value for key, value in item.items() if key != "id"}
            arguments = json.dumps(body, ensure_ascii=False, sort_keys=True)
            lines.append((kind, arguments, item.get("status", "unknown")))
    return header, lines, final


def render(client: str, raw: str, prompt: str) -> str:
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    parse = claude_code if client == "claude-code" else codex
    header, calls, final = parse(events)
    out = ["client: " + client]
    for key in ("version", "model", "result"):
        if header.get(key):
            out.append("%s: %s" % (key, header[key]))
    out += ["", "## prompt", "", prompt.rstrip("\n"), "", "## tool calls", ""]
    for number, (name, arguments, state) in enumerate(calls, 1):
        out.append("[%d] %s (%s)" % (number, name, state))
        out.append("    " + _cut(arguments.replace("\n", "\\n")))
    out += ["", "## final message", "", final.rstrip("\n"), ""]
    return "\n".join(out)


def _prefix(path: str, new: str, text: str) -> str:
    if not path:
        return text
    return re.sub(re.escape(path.rstrip("/")) + SEGMENT, new, text)


def scrub(text: str, plugins: list, root: str, home: str, host: str) -> str:
    for plugin in sorted(plugins, key=len, reverse=True):
        text = _prefix(plugin, "/plugin", text)
    text = SCRATCH.sub("/scratch", text)
    text = _prefix(root, "/work", text)
    text = _prefix(home, "~", text)
    if host:
        text = text.replace(host, "host")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client", choices=("claude-code", "codex"), required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--capture-root", required=True)
    parser.add_argument("--plugin-root", action="append", default=[])
    parser.add_argument("--home", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    raw = Path(args.raw).read_text(encoding="utf-8")
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    fields = (args.plugin_root, args.capture_root, args.home, args.hostname)
    events_text = scrub(raw, *fields)
    prompt_text = scrub(prompt, *fields)
    text = render(args.client, events_text, prompt_text)
    Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
