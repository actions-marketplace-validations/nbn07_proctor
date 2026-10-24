"""Decide what role a file plays: production code, test, harness, snapshot, or referee."""

from __future__ import annotations

import fnmatch
import re

_TEST_RES = [re.compile(p) for p in (
    r"(^|/)tests?/",
    r"(^|/)__tests__/",
    r"(^|/)spec/",
    r"(^|/)src/test/",
    r"(^|/)test_[^/]*\.py$",
    r"_test\.py$",
    r"\.(test|spec)\.[cm]?[jt]sx?$",
    r"_test\.go$",
    r"(^|/)[^/]*Tests?\.(java|kt|cs|swift)$",
    r"_spec\.rb$",
    r"_test\.rb$",
    r"(^|/)tests/[^/]*\.rs$",
)]

# Files that decide *how* tests are collected, run, or reported.
_HARNESS_NAMES = {
    "conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "noxfile.py",
    ".coveragerc", "codecov.yml", ".codecov.yml", "package.json", "Makefile", "makefile",
    "Jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "build.gradle.kts", ".mocharc.js", ".mocharc.json",
    ".mocharc.yml", ".nycrc", ".nycrc.json", "karma.conf.js", "phpunit.xml", "justfile",
}
_HARNESS_GLOBS = [
    "jest.config.*", "vitest.config.*", "vite.config.*", "playwright.config.*",
    "cypress.config.*", ".github/workflows/*", ".circleci/*", "*.bazel", "BUILD",
]

_SNAPSHOT_RES = [re.compile(p) for p in (
    r"(^|/)__snapshots__/", r"\.snap$", r"(^|/)golden/", r"\.golden$",
    r"(^|/)(expected|approved)(_outputs?)?/", r"\.approved\.", r"(^|/)cassettes/",
)]

# Files that judge the agent. Editing these is editing the referee.
_REFEREE_RES = [re.compile(p) for p in (
    r"(^|/)\.proctor\.toml$", r"(^|/)\.proctor/", r"(^|/)proctor\.toml$",
    r"(^|/)\.claude/settings(\.local)?\.json$",
)]

_SOURCE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt",
    ".cs", ".rb", ".php", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".scala", ".ex",
    ".exs", ".lua", ".dart",
}


def _base(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def is_referee(path: str) -> bool:
    return any(r.search(path) for r in _REFEREE_RES)


def is_harness(path: str) -> bool:
    b = _base(path)
    if b in _HARNESS_NAMES:
        return True
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(b, g) for g in _HARNESS_GLOBS)


def is_snapshot(path: str) -> bool:
    return any(r.search(path) for r in _SNAPSHOT_RES)


def is_test(path: str) -> bool:
    if is_harness(path) or is_snapshot(path):
        return False
    return any(r.search(path) for r in _TEST_RES)


def is_source(path: str) -> bool:
    if is_test(path) or is_harness(path) or is_snapshot(path):
        return False
    return any(path.endswith(e) for e in _SOURCE_EXT)


def role(path: str) -> str:
    if is_referee(path):
        return "referee"
    if is_harness(path):
        return "harness"
    if is_snapshot(path):
        return "snapshot"
    if is_test(path):
        return "test"
    if is_source(path):
        return "source"
    return "other"


def language(path: str) -> str:
    ext = "." + path.rsplit(".", 1)[-1] if "." in _base(path) else ""
    return {
        ".py": "python", ".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".mjs": "js",
        ".cjs": "js", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "java", ".cs": "csharp",
        ".rb": "ruby", ".php": "php",
    }.get(ext, "other")
