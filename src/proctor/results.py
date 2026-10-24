"""Read real pass/fail counts out of test runs. Never trust the agent's summary.

Two sources, in order of trust:

1. Machine-readable reports written *during this run*: JUnit XML (Maven
   Surefire/Failsafe, Gradle, pytest --junitxml, ctest --output-junit,
   GoogleTest --gtest_output=xml, jest-junit, go-junit-report, …) and .NET TRX.
   Files older than the run are ignored, so a stale report can't stand in for a
   real one.
2. The runner's console summary: pytest, unittest, jest, vitest, mocha, TAP,
   go, cargo, Maven, ctest, GoogleTest, Catch2 and `dotnet test`.
"""

from __future__ import annotations

import glob
import os
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, List, Optional


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
    reports: int = 0  # number of fresh XML reports read

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
    m = [x for x in re.findall(r"^(?:=+ )?(\d+ [\w ,]+?|no tests ran) in [\d.]+s\b", out, re.M)
         if re.search(r"\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b", x) or x == "no tests ran"]
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
    # ctest:  "75% tests passed, 1 tests failed out of 4"
    m = re.findall(r"^\d+% tests passed, (\d+) tests? failed out of (\d+)", out, re.M)
    if m:
        r.framework = "ctest"
        failed, total = int(m[-1][0]), int(m[-1][1])  # "out of N" already excludes disabled tests
        r.skipped = len(re.findall(r"^\s*\d+ - .*\((?:Disabled|Skipped|Not Run)\)\s*$", out, re.M))
        r.failed, r.passed = failed, max(0, total - failed)
        return r
    if re.search(r"^No tests were found!!!", out, re.M):
        r.framework = "ctest"
        return r
    # Maven Surefire/Failsafe: last "Tests run: 12, Failures: 1, Errors: 0, Skipped: 2" is the aggregate.
    m = re.findall(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)(?!.*Time elapsed)", out)
    if m:  # one aggregate line per module
        r.framework = "maven"
        for t, f, e, s_ in (map(int, x) for x in m):
            r.failed += f + e
            r.skipped += s_
            r.passed += max(0, t - f - e - s_)
        return r
    # JUnit 4 JUnitCore / Ant:  "OK (3 tests)"  |  "Tests run: 4,  Failures: 1"
    m = re.findall(r"^Tests run: (\d+),\s+Failures: (\d+)\s*$", out, re.M)
    if m:
        r.framework = "junit"
        r.failed = int(m[-1][1])
        r.passed = max(0, int(m[-1][0]) - r.failed)
        return r
    m = re.findall(r"^OK \((\d+) tests?\)", out, re.M)
    if m:
        r.framework = "junit"
        r.passed = int(m[-1])
        return r
    # GoogleTest (one or more binaries)
    if re.search(r"^\[=+\] \d+ tests? from \d+ test (?:suites?|cases?) ran", out, re.M):
        r.framework = "gtest"
        r.passed = sum(int(x) for x in re.findall(r"^\[  PASSED  \] (\d+) tests?\.", out, re.M))
        r.failed = sum(int(x) for x in re.findall(r"^\[  FAILED  \] (\d+) tests?, listed below", out, re.M))
        r.skipped = sum(int(x) for x in re.findall(r"^\[  SKIPPED \] (\d+) tests?, listed below", out, re.M))
        r.skipped += sum(int(x) for x in re.findall(r"YOU HAVE (\d+) DISABLED TESTS?", out))
        return r
    # dotnet test:  "Failed!  - Failed:     1, Passed:    11, Skipped:     0, Total:    12"
    m = re.findall(r"(?:Passed|Failed)!\s+-\s+Failed:\s+(\d+),\s+Passed:\s+(\d+),\s+Skipped:\s+(\d+),\s+Total:\s+(\d+)", out)
    if m:
        r.framework = "dotnet"
        for f, p, s, _ in m:
            r.failed += int(f); r.passed += int(p); r.skipped += int(s)
        return r
    m = re.findall(r"^Total tests:\s*(\d+)\s*\n\s*Passed:\s*(\d+)\s*\n\s*Failed:\s*(\d+)", out, re.M)
    if m:  # older vstest summary
        r.framework = "dotnet"
        r.passed, r.failed = int(m[-1][1]), int(m[-1][2])
        return r
    # Catch2:  "test cases: 3 | 2 passed | 1 failed"  /  "All tests passed (5 assertions in 3 test cases)"
    m = re.findall(r"^test cases:\s+(\d+)\s+\|\s+(\d+) passed\s+\|\s+(\d+) failed", out, re.M)
    if m:
        r.framework = "catch2"
        r.passed, r.failed = int(m[-1][1]), int(m[-1][2])
        return r
    m = re.findall(r"^All tests passed \(\d+ assertions? in (\d+) test cases?\)", out, re.M)
    if m:
        r.framework = "catch2"
        r.passed = int(m[-1])
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


# ------------------------------------------------------------------ XML reports

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_report(path: str):
    """Return (passed, failed, skipped) from a JUnit XML or .NET TRX file, or None if unreadable."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    tag = _local(root.tag)
    if tag == "TestRun":  # .NET TRX
        for el in root.iter():
            if _local(el.tag) == "Counters":
                a = el.attrib
                failed = int(a.get("failed", 0)) + int(a.get("error", 0)) + int(a.get("timeout", 0)) + int(a.get("aborted", 0))
                passed = int(a.get("passed", 0))
                skipped = int(a.get("notExecuted", 0)) + int(a.get("inconclusive", 0))
                return passed, failed, skipped
        return None
    cases = [el for el in root.iter() if _local(el.tag) == "testcase"]
    if cases:
        p = f = s = 0
        for c in cases:
            kids = {_local(k.tag) for k in c}
            status = c.attrib.get("status", "").lower()
            if kids & {"failure", "error"} or status in ("fail", "failed", "error"):
                f += 1
            elif "skipped" in kids or status in ("skipped", "notrun", "disabled") or c.attrib.get("result") == "suppressed":
                s += 1
            else:
                p += 1
        return p, f, s
    suites = [el for el in root.iter() if _local(el.tag) == "testsuite"] or ([root] if tag == "testsuites" else [])
    if suites:
        t = sum(int(x.attrib.get("tests", 0)) for x in suites)
        f = sum(int(x.attrib.get("failures", 0)) + int(x.attrib.get("errors", 0)) for x in suites)
        s = sum(int(x.attrib.get("skipped", x.attrib.get("disabled", 0))) for x in suites)
        return max(0, t - f - s), f, s
    return None


AUTO_REPORTS = {
    "mvn": ["**/target/surefire-reports/TEST-*.xml", "**/target/failsafe-reports/TEST-*.xml"],
    "./mvnw": ["**/target/surefire-reports/TEST-*.xml", "**/target/failsafe-reports/TEST-*.xml"],
    "gradle": ["**/build/test-results/**/*.xml"],
    "./gradlew": ["**/build/test-results/**/*.xml"],
    "dotnet": ["**/TestResults/**/*.trx"],
    "bazel": ["bazel-testlogs/**/test.xml"],
}


def _head(command: str) -> str:
    """Program name of the last command in a chain: `cmake --build b && ctest` -> `ctest`."""
    last = re.split(r"&&|\|\||;", command)[-1]
    parts = last.split()
    if parts and parts[0] in ("cd", "env", "time", "exec"):
        parts = parts[1:] if parts[0] != "cd" else []
    while parts and "=" in parts[0] and not parts[0].startswith(("./", "/")):  # skip FOO=bar prefixes
        parts = parts[1:]
    return parts[0] if parts else ""


def fresh_reports(cwd: str, patterns: Iterable[str], since: float) -> List[str]:
    out: List[str] = []
    for pat in patterns:
        for p in glob.glob(os.path.join(cwd, pat), recursive=True):
            try:
                if os.path.isfile(p) and os.path.getmtime(p) >= since - 1:
                    out.append(p)
            except OSError:
                pass
            if len(out) > 5000:
                return out
    return sorted(set(out))


def run(command: str, cwd: str, timeout: int = 1800, reports: Optional[List[str]] = None,
        extra_env: Optional[dict] = None) -> RunResult:
    t0 = time.time()
    try:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")  # no .pyc copies of sealed tests
        env.update(extra_env or {})
        p = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        output, code = (p.stdout or "") + "\n" + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired as e:
        output, code = f"proctor: timed out after {timeout}s\n{e.stdout or ''}", 124
    r = parse(output, code)
    patterns = list(reports or []) or AUTO_REPORTS.get(_head(command), [])
    if patterns:
        files = fresh_reports(cwd, patterns, t0)
        got = [x for x in (parse_report(f) for f in files) if x]
        if got:  # a report written during this run beats console scraping
            r.passed, r.failed, r.skipped = (sum(x[i] for x in got) for i in range(3))
            r.framework, r.reports = "junit-xml" if not files[0].endswith(".trx") else "trx", len(got)
    r.command, r.exit_code, r.seconds = command, code, round(time.time() - t0, 2)
    r.tail = "\n".join(re.sub(r"\x1b\[[0-9;]*m", "", output).strip().splitlines()[-25:])
    return r


def _stems(files) -> List[str]:
    out = []
    for f in files:
        base = os.path.basename(f)
        for suf in (".test.", ".spec."):
            base = base.split(suf)[0]
        out.append(base.split(".")[0])
    return list(dict.fromkeys(out))


def can_target(command: str) -> bool:
    """Whether `with_files` can restrict this runner to the sealed tests."""
    if "{files}" in command or "{names}" in command or "{names_csv}" in command:
        return True
    return _head(command) not in ("go", "cargo", "make", "tox", "nox", "just", "ctest", "bazel", "meson",
                                  "ninja", "cmake", "", "bash", "sh")


def with_files(command: str, files) -> str:
    files = list(files)
    quoted = " ".join(shlex.quote(f) for f in files)
    names = _stems(files)
    if any(k in command for k in ("{files}", "{names}", "{names_csv}")):
        return (command.replace("{files}", quoted).replace("{names_csv}", ",".join(names))
                .replace("{names}", "|".join(names)))
    head = _head(command)
    if not can_target(command):
        return command  # the full suite runs with the sealed tests present; see exam.verify
    if head in ("mvn", "./mvnw"):
        return f"{command} -Dtest={','.join(names)} -Dsurefire.failIfNoSpecifiedTests=false"
    if head in ("gradle", "./gradlew"):
        return command + "".join(f" --tests {shlex.quote('*' + n)}" for n in names)
    if head == "dotnet":
        flt = "|".join(f"FullyQualifiedName~{n}" for n in names)
        return f"{command} --filter {shlex.quote(flt)}"
    if head in ("npm", "yarn", "pnpm", "bun") and " -- " not in command:
        return f"{command} -- {quoted}"
    return f"{command} {quoted}"
