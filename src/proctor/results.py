"""Read real pass/fail counts out of test-runner output. Never trust the agent's summary."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class RunResult:
    command: str
    exit_code: int
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    framework: str = "unknown"
    seconds: float = 0.0
    tail: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def rate(self) -> Optional[float]:
        if self.total == 0:
            return None if self.exit_code == 0 else 0.0
        return self.passed / self.total

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.total > 0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["total"], d["rate"] = self.total, self.rate
        return d


def _num(pattern: str, text: str) -> int:
    ms = re.findall(pattern, text)
    return int(ms[-1]) if ms else 0


def parse(output: str, exit_code: int = 0) -> RunResult:
    out = re.sub(r"\x1b\[[0-9;]*m", "", output)
    r = RunResult(command="", exit_code=exit_code)

    # pytest:  "=== 3 failed, 10 passed, 1 skipped in 0.12s ==="
    m = re.findall(r"^(?:=+ )?((?:\d+ (?:passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?)(?:, )?)+|no tests ran) in [\d.]+s", out, re.M)
    if m:
        s = m[-1]
        r.framework = "pytest"
        r.passed = _num(r"(\d+) passed", s)
        r.failed = _num(r"(\d+) failed", s) + _num(r"(\d+) errors?", s)
        r.skipped = _num(r"(\d+) skipped", s) + _num(r"(\d+) xfailed", s) + _num(r"(\d+) deselected", s)
        return r
    # jest:  "Tests:       1 failed, 1 skipped, 4 passed, 6 total"
    m = re.findall(r"^Tests:\s+(.*total)", out, re.M)
    if m:
        s = m[-1]
        r.framework = "jest"
        r.passed, r.failed = _num(r"(\d+) passed", s), _num(r"(\d+) failed", s)
        r.skipped = _num(r"(\d+) skipped", s) + _num(r"(\d+) todo", s)
        return r
    # vitest:  "Tests  2 failed | 5 passed | 1 skipped (8)"
    m = re.findall(r"^\s*Tests\s+(.*\(\d+\))", out, re.M)
    if m:
        s = m[-1]
        r.framework = "vitest"
        r.passed, r.failed = _num(r"(\d+) passed", s), _num(r"(\d+) failed", s)
        r.skipped = _num(r"(\d+) skipped", s) + _num(r"(\d+) todo", s)
        return r
    # cargo:  "test result: FAILED. 3 passed; 1 failed; 2 ignored;"
    m = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", out)
    if m:
        r.framework = "cargo"
        for p, f, i in m:
            r.passed += int(p); r.failed += int(f); r.skipped += int(i)
        return r
    # go test -v
    if re.search(r"^(?:--- (?:PASS|FAIL|SKIP)|ok\s+\S+|FAIL\s+\S+)", out, re.M):
        r.framework = "go"
        r.passed = len(re.findall(r"^\s*--- PASS", out, re.M))
        r.failed = len(re.findall(r"^\s*--- FAIL", out, re.M))
        r.skipped = len(re.findall(r"^\s*--- SKIP", out, re.M))
        if r.passed + r.failed == 0:  # non-verbose: count packages
            r.passed = len(re.findall(r"^ok\s+\S+", out, re.M))
            r.failed = len(re.findall(r"^FAIL\s+\S+", out, re.M))
        return r
    # mocha:  "5 passing", "2 failing", "1 pending"
    if re.search(r"^\s+\d+ passing", out, re.M):
        r.framework = "mocha"
        r.passed, r.failed = _num(r"(\d+) passing", out), _num(r"(\d+) failing", out)
        r.skipped = _num(r"(\d+) pending", out)
        return r
    # unittest:  "Ran 7 tests in 0.001s" + "FAILED (failures=1, errors=1, skipped=2)" | "OK"
    m = re.findall(r"^Ran (\d+) tests? in", out, re.M)
    if m:
        r.framework = "unittest"
        total = int(m[-1])
        r.failed = _num(r"failures=(\d+)", out) + _num(r"errors=(\d+)", out)
        r.skipped = _num(r"skipped=(\d+)", out)
        r.passed = max(0, total - r.failed - r.skipped)
        return r
    # node --test / TAP:  "# pass 4", "# fail 1"
    if re.search(r"^# (?:pass|fail) \d+", out, re.M):
        r.framework = "tap"
        r.passed, r.failed = _num(r"(?m)^# pass (\d+)", out), _num(r"(?m)^# fail (\d+)", out)
        r.skipped = _num(r"(?m)^# skip(?:ped)? (\d+)", out)
        return r
    return r


def run(command: str, cwd: str, timeout: int = 1800) -> RunResult:
    t0 = time.time()
    try:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # no .pyc copies of sealed tests
        p = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        output, code = (p.stdout or "") + "\n" + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired as e:
        output, code = f"proctor: timed out after {timeout}s\n{e.stdout or ''}", 124
    r = parse(output, code)
    r.command, r.exit_code, r.seconds = command, code, round(time.time() - t0, 2)
    r.tail = "\n".join(re.sub(r"\x1b\[[0-9;]*m", "", output).strip().splitlines()[-25:])
    # A suite that "passed" while running zero tests is not a pass.
    return r


def with_files(command: str, files) -> str:
    quoted = " ".join(shlex.quote(f) for f in files)
    if "{files}" in command:
        return command.replace("{files}", quoted)
    head = command.split()[0] if command.split() else ""
    if head in ("go", "cargo", "make", "tox", "nox", "just", "mvn", "gradle", "./gradlew"):
        return command  # these runners can't target files; the full suite includes sealed tests
    if head in ("npm", "yarn", "pnpm", "bun") and " -- " not in command:
        return f"{command} -- {quoted}"
    return f"{command} {quoted}"
