"""One-command setup for coding agents other than Claude Code.

Every target is idempotent: proctor's text lives between marker comments and is
replaced, never duplicated, when you run the install again.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List

from .exam import detect_test_command

BEGIN, END = "<!-- proctor:begin -->", "<!-- proctor:end -->"

GUIDANCE = """## Test integrity (proctor)

This repository is checked by [proctor](https://github.com/nbn07/proctor). Before you report a task as done:

1. Run `proctor scan` (or call the `proctor_scan` MCP tool) and resolve every finding.
2. Fix the code, not the evaluation: do not skip, delete or weaken tests, special-case test inputs, or edit the
   test harness, CI configuration or `.proctor.toml` to make a check pass.
3. If changing a test is genuinely part of the task, say so to the user and add
   `proctor: allow <RULE> -- <reason>` on that line so a reviewer can see it.
"""

MCP_SERVER = {"command": "proctor", "args": ["mcp"]}


def _upsert_block(path: str, body: str, prefix: str = "") -> str:
    block = f"{BEGIN}\n{body.rstrip()}\n{END}\n"
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if BEGIN in text and END in text:
        text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", lambda _: block, text, flags=re.S)
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else prefix) + block
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _merge_json(path: str, key: str, name: str, value: dict) -> str:
    data: Dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().strip()
        data = json.loads(raw) if raw else {}
    data.setdefault(key, {})[name] = value
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    return path


def install_cursor(root: str) -> List[str]:
    rule = os.path.join(root, ".cursor", "rules", "proctor.mdc")
    os.makedirs(os.path.dirname(rule), exist_ok=True)
    with open(rule, "w", encoding="utf-8") as fh:
        fh.write("---\ndescription: Keep tests honest; run proctor before finishing\nalwaysApply: true\n---\n\n"
                 + GUIDANCE)
    return [rule, _merge_json(os.path.join(root, ".cursor", "mcp.json"), "mcpServers", "proctor", MCP_SERVER)]


def install_agents_md(root: str) -> List[str]:
    """AGENTS.md is read by Codex, Jules, Amp, Cursor, Zed, Aider (via read:) and others."""
    return [_upsert_block(os.path.join(root, "AGENTS.md"), GUIDANCE, prefix="# Agent guidelines\n\n")]


CODEX_TOML = '[mcp_servers.proctor]\ncommand = "proctor"\nargs = ["mcp"]\n'


def install_codex(root: str) -> List[str]:
    return install_agents_md(root)


def install_copilot(root: str) -> List[str]:
    instr = _upsert_block(os.path.join(root, ".github", "copilot-instructions.md"), GUIDANCE)
    vs = _merge_json(os.path.join(root, ".vscode", "mcp.json"), "servers", "proctor",
                     {"type": "stdio", **MCP_SERVER})
    return [instr, vs]


def install_aider(root: str) -> List[str]:
    path = os.path.join(root, ".aider.conf.yml")
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    lines = [l for l in text.splitlines() if not re.match(r"^\s*#\s*proctor\b", l)]
    has = lambda key: any(re.match(rf"^\s*{key}\s*:", l) for l in lines)
    added = ["# proctor: run the integrity scan with the tests after every edit"]
    if not has("test-cmd"):
        added.append(f"test-cmd: \"proctor scan --quiet && {detect_test_command(root)}\"")
    if not has("auto-test"):
        added.append("auto-test: true")
    if not has("read"):
        added.append("read: [AGENTS.md]")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join([l for l in lines if l.strip()] + added) + "\n")
    return [path] + install_agents_md(root)


def install_openhands(root: str) -> List[str]:
    return [_upsert_block(os.path.join(root, ".openhands", "microagents", "repo.md"), GUIDANCE)]


def install_windsurf(root: str) -> List[str]:
    return [_upsert_block(os.path.join(root, ".windsurf", "rules", "proctor.md"), GUIDANCE)]


TARGETS = {
    "cursor": (install_cursor, "rule (.cursor/rules/proctor.mdc) + MCP server (.cursor/mcp.json)"),
    "codex": (install_codex, "AGENTS.md guidance; add the MCP server to ~/.codex/config.toml (printed below)"),
    "copilot": (install_copilot, ".github/copilot-instructions.md + VS Code MCP server (.vscode/mcp.json)"),
    "aider": (install_aider, ".aider.conf.yml runs proctor with your tests after every edit + AGENTS.md"),
    "openhands": (install_openhands, ".openhands/microagents/repo.md"),
    "windsurf": (install_windsurf, ".windsurf/rules/proctor.md"),
    "agents-md": (install_agents_md, "AGENTS.md guidance for any agent that reads it"),
}
