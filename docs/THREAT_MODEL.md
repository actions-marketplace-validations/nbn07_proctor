# Threat model

Proctor is built for the common case: **an optimizing agent, not a malicious one.** Agents under pressure to make a check go green take the shortest path. That path usually runs through the tests, the harness or a hard-coded answer, and it usually leaves a recognizable trace in the diff. Proctor makes those traces impossible to miss and raises the cost of the shortcut.

## What proctor reliably catches

- Direct edits to tests: deletion, skipping, focusing, weakening, tautologies, commented-out assertions, changed expected values.
- Harness manipulation in the files most ecosystems use: pytest, jest, vitest, mocha, npm scripts, coverage config, CI workflows.
- Result forgery: report rewriting hooks, `exit(0)` in the harness, monkey-patched assertion methods, always-equal objects, replaced timers.
- Special-casing that uses the literal values from your tests.
- Overfitting to the visible tests, measured empirically in exam mode, whatever technique the agent used.
- Loosening proctor itself: config is always read from the base revision, so editing `.proctor.toml` can't change the current verdict, and the edit is its own `P015` finding.

## What it doesn't catch, and why

| Gap | Why | Mitigation |
|---|---|---|
| Cheats spread across files or built from computed values (`chr(77)+"CM…"`) | Proctor matches text, it doesn't evaluate programs | Exam mode measures the outcome, not the technique |
| An agent that reads sealed tests from git history | Tracked files live in `.git` | Keep held-out tests untracked or outside the sandbox ([EXAM_MODE.md](EXAM_MODE.md)) |
| An agent that disables proctor and then removes the evidence | It has the same permissions you do | Run `proctor` in CI on the pushed branch, not only in the agent's sandbox. Config edits are themselves findings (`P015`) |
| Tests that were weak from the start | Proctor judges the *change*, not the suite | Mutation testing (roadmap) |
| Legitimate test deletions and skips | Humans do these on purpose | Waivers with a written reason stay visible in every report |

## Why no LLM judge

An LLM reviewer is a useful second opinion, and you're free to add one. It's not a referee, though. The thing being judged is itself a language model, and it can explain, persuade, or inject instructions into comments that the judge reads. Proctor's verdicts come only from regular expressions, diff structure and real test-runner output, so the same input always gets the same verdict, and nothing in the code under review can talk it out of one.

## Reporting a bypass

A new way to slip past proctor is a gift. Open an issue or PR with the diff in `tests/fixtures/cheats/`. If the bypass works against the GitHub Action in a way that could hide a malicious change in someone's CI, please report it privately (see [SECURITY.md](../SECURITY.md)).
