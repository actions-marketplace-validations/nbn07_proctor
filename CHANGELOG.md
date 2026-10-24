# Changelog

## 0.2.0 — 2026-10-24

- **`proctor bench`**: benchmark any coding agent on your own codebase. `mine` turns bug-fix commits into tasks whose hidden exam is the tests that shipped with each fix (for Python, the exact test functions added or changed); `--validate` keeps tasks whose hidden tests fail before the fix and pass after. `run` executes agents in history-free sandboxes and scores each attempt as resolved, flagged, failed or regressed; `report` builds a leaderboard. Built-in `gold` and `noop` agents for sanity checks.
- **`proctor diff-test`**: for refactors, runs the old and new versions of every changed Python function side by side on hundreds of inputs (calls from your tests and code, mutations, type hints) and reports where behavior differs, including code that matches the old behavior only on tested inputs.
- **`proctor mcp`**: a dependency-free MCP server (stdio) with `proctor_scan`, `proctor_verify`, `proctor_diff_test`, `proctor_status` and `proctor_rules`; verified with the official MCP Python SDK client.
- **`proctor install cursor | copilot | codex | aider | openhands | windsurf | agents-md | mcp | all`**: one-command setup for every major coding agent. Removing proctor's guidance from those files is a `P015` finding.
- Answer-key rule (`P011`) no longer treats protocol and identifier vocabulary (`"tools/list"`, `"user.created"`) or values nested inside returned structures as memorized answers.
- pytest summaries with subtests (`586 passed, 10080 subtests passed`) are parsed correctly.

## 0.1.0 — 2026-10-24

First public release.

- `proctor scan`: 21 deterministic rules for evaluation tampering across Python, JS/TS, Go, Rust, Java/Kotlin, C#, C/C++ and Ruby, with text, Markdown, JSON and SARIF output.
- Exam mode (`seal` / `verify` / `unseal` / `status`): held-out tests, generalization gap, pristine-harness re-runs that measure harness inflation, contamination detection (`P100`, `P101`) and `--split` for random reproducible holdouts.
- Real result parsing for pytest, unittest, jest, vitest, mocha, TAP, go, cargo, Maven, JUnit, CTest, GoogleTest, Catch2 and `dotnet test`, plus JUnit XML and .NET TRX reports (only files written during the run are trusted).
- Scanner coverage for C/C++ (GoogleTest, Catch2, doctest, Boost.Test, Unity, CMocka, CMake/CTest, Bazel), Java/Kotlin (JUnit 4/5, TestNG, AssertJ, Maven, Gradle) and C# (xUnit, NUnit, MSTest, FluentAssertions).
- Exam mode targets sealed tests automatically for Maven, Gradle and `dotnet test`, and uses full-suite subtraction for runners that can't target files.
- Published on PyPI as `agent-proctor` (the command is `proctor`).
- Integrations: Claude Code `SessionStart` + `Stop` hooks (`proctor install claude`), git pre-commit (`proctor install git`), pre-commit framework hook and a GitHub Action with sticky PR comments.
- In-line waivers (`# proctor: allow P003 -- reason`) that stay visible in every report.
- Rogues' gallery of 43 cheats and 17 honest controls across six languages, plus a noise-floor benchmark on 1,649 human commits from 11 projects (2.2% blocked, all genuine test removals or skips).
