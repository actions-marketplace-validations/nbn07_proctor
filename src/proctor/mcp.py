"""`proctor mcp`: a Model Context Protocol server over stdio, with zero dependencies.

Any MCP-capable agent (Claude Code, Cursor, VS Code / Copilot, Codex, Windsurf,
Zed, OpenHands…) can call proctor itself before it claims a task is done:

    proctor_scan     did my change tamper with how it will be judged?
    proctor_verify   run the sealed exam (if one is set up) and report the gap
    proctor_status   is an exam sealed here?
    proctor_rules    what counts as tampering?

Protocol: JSON-RPC 2.0, one message per line on stdin/stdout. Nothing else is
ever written to stdout.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Dict, Optional

from . import __version__, exam, report
from . import diff as gitdiff
from .engine import Config, rule_table, scan_repo

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "proctor checks whether a code change games its own evaluation (skipped, deleted or weakened tests, "
    "rigged test harnesses, special-cased test inputs). Call proctor_scan before you report a coding task "
    "as done. If the verdict is FAIL, revert the flagged edits and fix the implementation instead. "
    "Never edit tests, CI or .proctor.toml just to make proctor pass."
)

_PATH = {"type": "string", "description": "Repository directory (default: the server's working directory)."}
TOOLS = [
    {
        "name": "proctor_scan",
        "title": "Check a change for test tampering",
        "description": ("Scan everything that changed since `base` (default: the start of this agent session if "
                        "proctor's session hook recorded it, else HEAD), including uncommitted and untracked files. "
                        "Returns a PASS / WARN / FAIL verdict and each finding with file, line and reason. "
                        "Call this before reporting a task as done."),
        "inputSchema": {"type": "object", "properties": {
            "path": _PATH,
            "base": {"type": "string", "description": "Git ref to compare against."}}},
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "proctor_verify",
        "title": "Run the sealed exam",
        "description": ("If held-out tests were sealed with `proctor seal`, run the visible and sealed tests under "
                        "the original test harness and report the generalization gap. Restores everything after."),
        "inputSchema": {"type": "object", "properties": {"path": _PATH}},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    },
    {
        "name": "proctor_diff_test",
        "title": "Check a refactor preserved behavior",
        "description": ("For a refactor, run the old and new versions of every changed Python function on hundreds "
                        "of inputs (from existing calls, their mutations, and type hints) and report inputs where "
                        "behavior differs. Flags code that matches the old behavior only on the inputs the tests use."),
        "inputSchema": {"type": "object", "properties": {
            "path": _PATH,
            "base": {"type": "string", "description": "Git ref whose behavior must be preserved (default HEAD)."},
            "samples": {"type": "integer", "description": "Inputs per function (default 300)."}}},
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "proctor_status",
        "title": "Is an exam sealed?",
        "description": "Report whether held-out tests are sealed for this repository, and which test command is used.",
        "inputSchema": {"type": "object", "properties": {"path": _PATH}},
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "proctor_rules",
        "title": "List tampering rules",
        "description": "List every rule proctor enforces, with its severity and the reason it exists.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
]


def _root(args: dict) -> str:
    return gitdiff.repo_root(os.path.abspath(args.get("path") or os.getcwd()))


def _session_base(root: str) -> Optional[str]:
    gd = gitdiff.git(["rev-parse", "--git-dir"], root, check=False).strip()
    p = os.path.join(gd if os.path.isabs(gd) else os.path.join(root, gd), "proctor", "session.json")
    if os.path.exists(p):
        try:
            with open(p) as fh:
                return json.load(fh).get("base")
        except (OSError, ValueError):
            return None
    return None


def tool_scan(args: dict) -> Dict[str, Any]:
    root = _root(args)
    base = args.get("base") or _session_base(root) or "HEAD"
    res = scan_repo(root, base=base, config=Config.load(root, rev=base))
    text = report.scan_text(res, color=False)
    if res.verdict == "FAIL":
        text += ("\n\nDo not report this task as done. Revert the flagged edits and fix the implementation. "
                 "If a flagged change is genuinely required, explain why to the user and add "
                 "`proctor: allow <RULE> -- <reason>` on that line.")
    return {"text": text, "data": res.to_dict(), "error": False}


def tool_verify(args: dict) -> Dict[str, Any]:
    root = _root(args)
    if not exam.load_manifest(root):
        return {"text": "No exam is sealed for this repository. A human seals held-out tests with "
                        "`proctor seal <tests>`; until then use proctor_scan.", "data": {"sealed": False},
                "error": False}
    res = exam.verify(root)
    return {"text": report.exam_text(res, color=False), "data": res.to_dict(), "error": False}


def tool_diff_test(args: dict) -> Dict[str, Any]:
    from . import difftest
    root = _root(args)
    res = difftest.diff_test(root, base=args.get("base") or "HEAD", samples=int(args.get("samples") or 300))
    return {"text": difftest.text_report(res), "data": res.to_dict(), "error": False}


def tool_status(args: dict) -> Dict[str, Any]:
    root = _root(args)
    m = exam.load_manifest(root)
    if not m:
        return {"text": "No exam sealed.", "data": {"sealed": False}, "error": False}
    # Paths of sealed files are not secret, but their contents are never returned.
    return {"text": f"Exam sealed at {(m.get('base') or '?')[:10]} with {len(m['sealed'])} hidden file(s). "
                    f"Test command: {m['test_command']}",
            "data": {"sealed": True, "files": len(m["sealed"]), "test_command": m["test_command"]}, "error": False}


def tool_rules(args: dict) -> Dict[str, Any]:
    rules = rule_table()
    text = "\n".join(f"{r['id']} [{r['severity']}] {r['title']}: {r['why']}" for r in rules)
    return {"text": text, "data": {"rules": rules}, "error": False}


HANDLERS = {"proctor_scan": tool_scan, "proctor_verify": tool_verify, "proctor_diff_test": tool_diff_test,
            "proctor_status": tool_status, "proctor_rules": tool_rules}


def handle(msg: dict) -> Optional[dict]:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notification (e.g. notifications/initialized): no reply
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "proctor", "title": "proctor", "version": __version__},
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in HANDLERS:
            return err(-32602, f"unknown tool: {name}")
        try:
            r = HANDLERS[name](args)
            return ok({"content": [{"type": "text", "text": r["text"]}], "structuredContent": r["data"],
                       "isError": r["error"]})
        except Exception as e:  # tool errors are results, not protocol errors
            return ok({"content": [{"type": "text", "text": f"proctor error: {type(e).__name__}: {e}"}],
                       "isError": True})
    return err(-32601, f"method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            batch = msg if isinstance(msg, list) else [msg]
            out = []
            for m in batch:
                try:
                    r = handle(m) if isinstance(m, dict) else None
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    r = {"jsonrpc": "2.0", "id": m.get("id"), "error": {"code": -32603, "message": "internal error"}}
                if r is not None:
                    out.append(r)
            if not out:
                continue
            reply = out if isinstance(msg, list) else out[0]
        stdout.write(json.dumps(reply) + "\n")
        stdout.flush()
    return 0
