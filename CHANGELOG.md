# Changelog

## 0.1.0 — 2026-10-24

First public release.

- `proctor scan`: 21 deterministic rules for evaluation tampering across Python, JS/TS, Go, Rust, Java, C# and Ruby, with text, Markdown, JSON and SARIF output.
- Exam mode (`seal` / `verify` / `unseal` / `status`): held-out tests, generalization gap, pristine-harness re-runs that measure harness inflation, contamination detection (`P100`, `P101`) and `--split` for random reproducible holdouts.
- Real result parsing for pytest, jest, vitest, go, cargo, mocha, unittest and TAP.
- Integrations: Claude Code `SessionStart` + `Stop` hooks (`proctor install claude`), git pre-commit (`proctor install git`), pre-commit framework hook and a GitHub Action with sticky PR comments.
- In-line waivers (`# proctor: allow P003 -- reason`) that stay visible in every report.
- Rogues' gallery of 25 cheats and 10 honest controls, plus a noise-floor benchmark on 899 human commits.
