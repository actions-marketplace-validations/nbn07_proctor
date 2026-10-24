# Changelog

## 0.1.0 — 2026-10-24

First public release.

- `proctor scan`: 21 deterministic rules for evaluation tampering across Python, JS/TS, Go, Rust, Java/Kotlin, C#, C/C++ and Ruby, with text, Markdown, JSON and SARIF output.
- Exam mode (`seal` / `verify` / `unseal` / `status`): held-out tests, generalization gap, pristine-harness re-runs that measure harness inflation, contamination detection (`P100`, `P101`) and `--split` for random reproducible holdouts.
- Real result parsing for pytest, unittest, jest, vitest, mocha, TAP, go, cargo, Maven, JUnit, CTest, GoogleTest, Catch2 and `dotnet test`, plus JUnit XML and .NET TRX reports (only files written during the run are trusted).
- Scanner coverage for C/C++ (GoogleTest, Catch2, doctest, Boost.Test, Unity, CMocka, CMake/CTest, Bazel), Java/Kotlin (JUnit 4/5, TestNG, AssertJ, Maven, Gradle) and C# (xUnit, NUnit, MSTest, FluentAssertions).
- Exam mode targets sealed tests automatically for Maven, Gradle and `dotnet test`, and uses full-suite subtraction for runners that can't target files.
- Integrations: Claude Code `SessionStart` + `Stop` hooks (`proctor install claude`), git pre-commit (`proctor install git`), pre-commit framework hook and a GitHub Action with sticky PR comments.
- In-line waivers (`# proctor: allow P003 -- reason`) that stay visible in every report.
- Rogues' gallery of 43 cheats and 17 honest controls across six languages, plus a noise-floor benchmark on 1,649 human commits from 11 projects (2.2% blocked, all genuine test removals or skips).
