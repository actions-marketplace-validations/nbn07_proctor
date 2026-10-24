"""Command-line interface."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import __version__
from . import diff as gitdiff
from . import exam, hooks, report
from .engine import Config, rule_table, scan_repo, scan_text

EXIT = {"PASS": 0, "WARN": 0, "FAIL": 1}


def _emit(text: str, output: Optional[str]) -> None:
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)


def cmd_scan(a) -> int:
    cwd = os.path.abspath(a.cwd)
    if a.diff:
        text = sys.stdin.read() if a.diff == "-" else open(a.diff, encoding="utf-8").read()
        try:
            root = gitdiff.repo_root(cwd)
        except gitdiff.GitError:
            root = None
        cfg = Config.load(root)
        if a.fail_on:
            cfg.fail_on = a.fail_on
        res = scan_text(text, root=root, base=a.diff, config=cfg)
    else:
        root = gitdiff.repo_root(cwd)
        cfg = Config.load(root, rev="HEAD" if a.staged else a.base)  # rules come from before the change
        if a.fail_on:
            cfg.fail_on = a.fail_on
        res = scan_repo(root, base=a.base, staged=a.staged, config=cfg)
    if a.quiet and res.verdict == "PASS":
        return 0
    fmt = a.format
    if fmt == "json":
        _emit(report.as_json(res), a.output)
    elif fmt == "markdown":
        _emit(report.scan_markdown(res), a.output)
    elif fmt == "sarif":
        _emit(report.sarif(res), a.output)
    else:
        _emit(report.scan_text(res, color=False if a.output else None), a.output)
    if os.environ.get("GITHUB_STEP_SUMMARY") and fmt != "markdown":
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report.scan_markdown(res) + "\n")
    return EXIT[res.verdict]


def cmd_seal(a) -> int:
    root = gitdiff.repo_root(os.path.abspath(a.cwd))
    m = exam.seal(root, a.paths, split=a.split, seed=a.seed, test_command=a.cmd, holdout_command=a.holdout_cmd)
    n = len(m["sealed"])
    print(f"proctor: sealed {n} file(s) out of the agent's sight")
    for e in m["sealed"][:20]:
        print(f"  🔒 {e['path']}")
    if n > 20:
        print(f"  … and {n - 20} more")
    print(f"  test command:    {m['test_command']}")
    if any(e["tracked"] for e in m["sealed"]):
        print("  note: sealed files are tracked by git; an agent that runs `git show HEAD:<path>` can still read them.\n"
              "        For a watertight exam keep held-out tests outside the repo (see docs/EXAM_MODE.md).")
    print("Now let the agent work. Then run `proctor verify`.")
    return 0


def cmd_verify(a) -> int:
    root = gitdiff.repo_root(os.path.abspath(a.cwd))
    res = exam.verify(root, test_command=a.cmd, holdout_command=a.holdout_cmd, pristine=not a.no_pristine,
                      timeout=a.timeout, run_scan=not a.no_scan)
    if a.format == "json":
        _emit(report.as_json(res), a.output)
    elif a.format == "markdown":
        _emit(report.exam_markdown(res), a.output)
    else:
        _emit(report.exam_text(res, color=False if a.output else None), a.output)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(report.exam_markdown(res) + "\n")
    return EXIT[res.verdict]


def cmd_unseal(a) -> int:
    root = gitdiff.repo_root(os.path.abspath(a.cwd))
    m = exam.unseal(root)
    print(f"proctor: restored {len(m['sealed'])} sealed file(s)")
    return 0


def cmd_status(a) -> int:
    root = gitdiff.repo_root(os.path.abspath(a.cwd))
    m = exam.load_manifest(root)
    if not m:
        print("proctor: no exam sealed for this repo")
        return 0
    print(f"proctor: exam sealed {m['created']} at {m['base'][:10] if m.get('base') else '?'}")
    for e in m["sealed"]:
        print(f"  🔒 {e['path']}")
    print(f"  test command: {m['test_command']}")
    return 0


def cmd_rules(a) -> int:
    for r in rule_table():
        print(f"{r['id']}  {r['severity']:<6}  {r['slug']:<20}  {r['title']}")
    return 0


def cmd_hook(a) -> int:
    if a.event == "session-start":
        return hooks.session_start()
    return hooks.stop()


def cmd_install(a) -> int:
    root = gitdiff.repo_root(os.path.abspath(a.cwd))
    if a.target == "claude":
        p = hooks.install_claude(root, local=a.local)
        print(f"proctor: Claude Code hooks written to {os.path.relpath(p, root)}")
        print("  SessionStart → snapshot the tree · Stop → block completion if the agent gamed its tests")
    else:
        p = hooks.install_git(root)
        print(f"proctor: git pre-commit hook installed at {os.path.relpath(p, root)}")
    return 0


INIT_TOML = """# proctor configuration — https://github.com/nbn07/proctor
# Severity that fails the run: "high" (default), "medium", "low" or "none".
fail_on = "high"

# Rules to turn off, by id or slug (see `proctor rules`).
disable = []

# Files that judge the agent (graders, eval sets, golden data). Any edit is a high finding.
protect = []  # e.g. ["evals/**", "scripts/grade.py"]

# Paths to ignore (glob).
exclude = ["vendor/*", "third_party/*"]

# Used by `proctor verify`. {files} is replaced with the sealed test paths.
# test_command = "python -m pytest -q"
# holdout_command = "python -m pytest -q {files}"
# min_holdout_pass = 1.0
"""


def cmd_init(a) -> int:
    root = gitdiff.repo_root(os.path.abspath(a.cwd))
    p = os.path.join(root, ".proctor.toml")
    if os.path.exists(p):
        print("proctor: .proctor.toml already exists")
    else:
        with open(p, "w") as fh:
            fh.write(INIT_TOML)
        print("proctor: wrote .proctor.toml")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="proctor", description="The exam proctor for AI coding agents.")
    p.add_argument("--version", action="version", version=f"proctor {__version__}")
    p.add_argument("-C", dest="cwd", default=".", help="run as if started in this directory")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("scan", help="scan a change for evaluation tampering")
    s.add_argument("--base", default="HEAD", help="compare the working tree against this ref (default: HEAD)")
    s.add_argument("--staged", action="store_true", help="scan staged changes only (pre-commit)")
    s.add_argument("--diff", help="scan a unified diff file instead of git ('-' for stdin)")
    s.add_argument("--format", "-f", choices=["text", "json", "markdown", "sarif"], default="text")
    s.add_argument("--output", "-o", help="write the report to a file")
    s.add_argument("--fail-on", choices=["high", "medium", "low", "none"])
    s.add_argument("--quiet", "-q", action="store_true", help="print nothing when the verdict is PASS")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("seal", help="hide held-out tests from the agent")
    s.add_argument("paths", nargs="+")
    s.add_argument("--split", type=float, help="hold out this fraction of the test files found under PATHS")
    s.add_argument("--seed", type=int, help="random seed for --split")
    s.add_argument("--cmd", help="command that runs the visible tests")
    s.add_argument("--holdout-cmd", help="command that runs the sealed tests ({files} = sealed paths)")
    s.set_defaults(fn=cmd_seal)

    s = sub.add_parser("verify", help="run visible + sealed tests under a pristine harness")
    s.add_argument("--cmd")
    s.add_argument("--holdout-cmd")
    s.add_argument("--no-pristine", action="store_true", help="don't restore harness files changed by the agent")
    s.add_argument("--no-scan", action="store_true", help="skip the integrity scan")
    s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--format", "-f", choices=["text", "json", "markdown"], default="text")
    s.add_argument("--output", "-o")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("unseal", help="restore sealed tests")
    s.set_defaults(fn=cmd_unseal)
    s = sub.add_parser("status", help="show the sealed exam, if any")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("rules", help="list detection rules")
    s.set_defaults(fn=cmd_rules)
    s = sub.add_parser("init", help="write a starter .proctor.toml")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("install", help="wire proctor into an agent or git")
    s.add_argument("target", choices=["claude", "git"])
    s.add_argument("--local", action="store_true", help="claude: write .claude/settings.local.json")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("hook", help="entry point for agent hooks (reads JSON on stdin)")
    s.add_argument("event", choices=["session-start", "stop"])
    s.set_defaults(fn=cmd_hook)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    a = parser.parse_args(argv)
    if not getattr(a, "fn", None):
        parser.print_help()
        return 0
    try:
        return a.fn(a)
    except (gitdiff.GitError, exam.ExamError, FileExistsError) as e:
        print(f"proctor: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
