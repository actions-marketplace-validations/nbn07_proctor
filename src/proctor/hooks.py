"""Agent integrations: Claude Code hooks and a git pre-commit hook.

Claude Code calls `proctor hook session-start` when a session begins (we
snapshot the tree) and `proctor hook stop` when the agent tries to finish. If
the agent tampered with its own evaluation, the stop is blocked and the agent
is told exactly what to undo, before a human ever sees "all tests pass".
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from typing import Optional

from . import diff as gitdiff
from .engine import Config, scan_repo
from .rules import HIGH


def _state_dir(root: str) -> str:
    gd = gitdiff.git(["rev-parse", "--git-dir"], root).strip()
    d = os.path.join(gd if os.path.isabs(gd) else os.path.join(root, gd), "proctor")
    os.makedirs(d, exist_ok=True)
    return d


def _read_stdin_json() -> dict:
    try:
        if sys.stdin and not sys.stdin.isatty():
            raw = sys.stdin.read()
            return json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        pass
    return {}


def session_start(cwd: Optional[str] = None) -> int:
    payload = _read_stdin_json()
    cwd = payload.get("cwd") or cwd or os.getcwd()
    try:
        root = gitdiff.repo_root(cwd)
    except gitdiff.GitError:
        return 0
    # `git stash create` snapshots tracked changes without touching the tree, so
    # pre-existing uncommitted work is not blamed on the agent.
    snap = gitdiff.git(["stash", "create"], root, check=False).strip()
    base = snap or gitdiff.git(["rev-parse", "HEAD"], root, check=False).strip()
    untracked = [p for p in gitdiff.git(["ls-files", "--others", "--exclude-standard", "-z"], root,
                                        check=False).split("\0") if p]
    if snap:  # keep the snapshot reachable so `git gc` can't collect it mid-session
        gitdiff.git(["update-ref", "refs/proctor/session-base", snap], root, check=False)
    with open(os.path.join(_state_dir(root), "session.json"), "w") as fh:
        json.dump({"base": base, "untracked": untracked, "session_id": payload.get("session_id")}, fh)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext":
        "This repository is watched by proctor. Changes that skip, delete, weaken or special-case tests, "
        "or that alter the test harness, are detected and will block completion. Fix the code, not the tests."}}))
    return 0


def stop(cwd: Optional[str] = None) -> int:
    payload = _read_stdin_json()
    cwd = payload.get("cwd") or cwd or os.getcwd()
    try:
        root = gitdiff.repo_root(cwd)
    except gitdiff.GitError:
        return 0
    sd = _state_dir(root)
    base = "HEAD"
    untracked = []
    sp = os.path.join(sd, "session.json")
    if os.path.exists(sp):
        with open(sp) as fh:
            st = json.load(fh)
        base = st.get("base") or "HEAD"
        untracked = list(st.get("untracked", []))
    cfg = Config.load(root, rev=base)
    cfg.exclude = list(cfg.exclude) + untracked
    try:
        res = scan_repo(root, base=base, config=cfg)
    except gitdiff.GitError:
        return 0
    if res.verdict != "FAIL":
        return 0
    blocking = [f for f in res.active if f.severity == HIGH] or res.active
    fp = hashlib.sha1("|".join(f"{f.rule}:{f.path}:{f.snippet}" for f in blocking).encode()).hexdigest()
    lp = os.path.join(sd, "last_block")
    last = open(lp).read().strip() if os.path.exists(lp) else ""
    if payload.get("stop_hook_active") and last == fp:
        # Already told the agent once and nothing changed: let it stop, but tell the human.
        sys.stderr.write(f"proctor: FAIL — {len(blocking)} unresolved integrity finding(s); run `proctor scan --base {base}`\n")
        return 0
    with open(lp, "w") as fh:
        fh.write(fp)
    lines = [f"proctor blocked completion: this change alters how the work is evaluated ({len(blocking)} finding(s))."]
    for f in blocking[:8]:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"- {f.rule} {f.title} at {loc}: {f.message}")
    lines.append("Revert these edits and fix the implementation instead. If a change is genuinely intended, "
                 "add `# proctor: allow <RULE> -- <reason>` on that line so a human can review the waiver.")
    print(json.dumps({"decision": "block", "reason": "\n".join(lines)}))
    return 0


def install_claude(root: str, local: bool = False) -> str:
    d = os.path.join(root, ".claude")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "settings.local.json" if local else "settings.json")
    data = {}
    if os.path.exists(path):
        with open(path) as fh:
            data = json.load(fh)
    hooks = data.setdefault("hooks", {})

    def ensure(event: str, cmd: str):
        groups = hooks.setdefault(event, [])
        for g in groups:
            for h in g.get("hooks", []):
                if h.get("command") == cmd:
                    return
        groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 120}]})

    ensure("SessionStart", "proctor hook session-start")
    ensure("Stop", "proctor hook stop")
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    return path


PRE_COMMIT = """#!/bin/sh
# installed by proctor — blocks commits that tamper with tests or the test harness
exec proctor scan --staged --quiet
"""


def install_git(root: str) -> str:
    gd = gitdiff.git(["rev-parse", "--git-path", "hooks"], root).strip()
    hooks_dir = gd if os.path.isabs(gd) else os.path.join(root, gd)
    os.makedirs(hooks_dir, exist_ok=True)
    path = os.path.join(hooks_dir, "pre-commit")
    if os.path.exists(path):
        with open(path) as fh:
            if "proctor" in fh.read():
                return path
        raise FileExistsError(f"{path} already exists; add `proctor scan --staged` to it manually")
    with open(path, "w") as fh:
        fh.write(PRE_COMMIT)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path
