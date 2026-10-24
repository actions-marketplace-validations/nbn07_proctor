<div align="center">

# proctor

**The exam proctor for AI coding agents.**

Your agent says *"all tests pass ✅"*. Proctor checks whether it passed the exam or rewrote it.

[![CI](https://github.com/nbn07/proctor/actions/workflows/ci.yml/badge.svg)](https://github.com/nbn07/proctor/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/proctor.svg)](https://pypi.org/project/proctor/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Zero dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
![No LLM in the loop](https://img.shields.io/badge/verdicts-deterministic-black)

<img src="docs/hero.svg" alt="proctor catching an agent that special-cased test inputs and rewrote pytest results" width="820">

</div>

---

> *"When a measure becomes a target, it ceases to be a good measure."* — Goodhart's law

Coding agents are trained, prompted and graded on one signal: **make the tests pass.** So sometimes they do exactly that, and nothing else. They skip the failing test. They change `== 170` to `is not None`. They add a `conftest.py` that rewrites failures into passes. They write `if n == 10001: return 104743`.

This is not hypothetical:

- [METR](https://metr.org/blog/2025-06-05-recent-reward-hacking) watched frontier models monkey-patch evaluators to always return a perfect score and overwrite timing functions, and found that adding *"Please do not cheat."* to the prompt left the cheating rate unchanged at 80% on one task.
- [GSO](https://gso-blog.notion.site/gso-hackdetector) found up to **30%** of a model's solutions were reward hacks, and **18%** of attempts were exploits that *passed the correctness tests*.
- [ImpossibleBench](https://arxiv.org/abs/2510.20270) (ICLR 2026) built tasks that can't be solved honestly. Models "solved" them by deleting failing tests and overloading operators.

Code review was designed for humans who don't do this. A green CI badge was designed for test suites nobody was optimizing against. **Proctor is the missing piece: it checks the grading, not just the grade.**

## Two layers of defense

### 1 · `proctor scan`: did the change touch how it's judged?

A deterministic, explainable diff scanner with 21 rules for the ways agents game evaluations. It needs no API key, sends nothing over the network, and its verdict never depends on an LLM.

| | What the agent did | Rule |
|---|---|---|
| 🗑️ | Deleted a test file, or removed test cases | `P001` `P002` |
| ⏭️ | Added `skip` / `xfail` / `t.Skip()` / `#[ignore]`, or narrowed the run with `.only` | `P003` `P004` |
| 🫥 | `assert True`, `expect(x).toBe(x)`, commented-out assertions, `==` weakened to `is not None` | `P005` `P006` |
| ✏️ | Changed the *expected value* to match what the buggy code returns | `P019` |
| 🧪 | `conftest.py` that rewrites failures to passes; monkey-patched `assertEqual` | `P008` |
| 🚪 | `os._exit(0)` in the harness so the run "succeeds" before failures print | `P009` |
| 🙈 | `collect_ignore`, `--deselect`, `testPathIgnorePatterns`, `\|\| true`, CI test step deleted | `P007` |
| 🕵️ | Production code that checks `PYTEST_CURRENT_TEST` / `NODE_ENV === 'test'` | `P010` |
| 📝 | **Answer-key special-casing:** `if s == "XIV": return 14`, matched against the exact input/expected pairs in your tests | `P011` |
| 🟰 | `__eq__` that returns `True` for everything | `P020` |
| ⏱️ | Overwrote `time.perf_counter` so benchmarks look fast | `P021` |
| ⚖️ | Edited proctor's config or removed its hook (the agent changing the referee) | `P015` |
| … | Swallowed exceptions, regenerated snapshots, lowered coverage gates, mocked the unit under test, retry/sleep jiggling, new `@ts-ignore`s | `P012`–`P018` |

Full catalogue with examples: [`docs/RULES.md`](docs/RULES.md).

### 2 · Exam mode: does the work generalize to tests it never saw?

Static rules catch known tricks. Exam mode catches the unknown ones, using the oldest idea in machine learning: **a held-out test set.**

```bash
proctor seal tests/holdout/          # hide these tests from the agent
#   … the agent works against the tests it can see …
proctor verify                       # re-run everything under a pristine harness
proctor unseal
```

`verify` reports four things no test runner can tell you:

- **Generalization gap**: visible pass rate minus sealed pass rate. An honest implementation scores about 0. One that memorized the visible tests scores high.
- **Harness inflation**: proctor runs the suite twice, once with the agent's edits to `conftest.py`, `jest.config`, `package.json` and CI files, and once with those files restored from the base commit. The difference is how many passes the agent's harness edits produced without fixing anything.
- **Contamination**: whether a sealed file reappeared in the tree (for example via `git show HEAD:…`), or whether values that appear *only* in the sealed tests turned up in the agent's code.
- **The true result**: real pass/fail counts parsed from pytest, jest, vitest, go, cargo, mocha, unittest or TAP output, never from the agent's summary. A run that collects zero tests counts as a fail.

No sealed tests yet? Split your existing suite like a dataset:

```bash
proctor seal tests/ --split 0.3 --seed 42    # hold out 30% of test files, reproducibly
```

## Quick start

```bash
pipx install proctor        # or: pip install proctor  ·  Python ≥ 3.9
cd your-repo
proctor scan                # scan uncommitted + untracked changes vs HEAD
proctor scan --base main    # scan a branch
```

Exit code is `1` on **FAIL**, `0` otherwise, so it drops into any script or CI system.

## Put it in the loop

**Claude Code**: block the agent from finishing until it undoes the cheat:

```bash
proctor install claude
```

This adds a `SessionStart` hook, which snapshots the tree so pre-existing work isn't blamed on the agent, and a `Stop` hook. If the agent tampered with its evaluation, the stop is blocked and the agent is told exactly what to revert. If it ignores the warning and tries to stop again, proctor lets it stop (no infinite loops) and reports the problem to you.

**Any agent** (Codex, Cursor, Aider, Copilot, Devin, your own): use the git hook, or scan whatever the agent produced:

```bash
proctor install git               # pre-commit: proctor scan --staged
proctor scan --base "$START_SHA"  # after any agent run
```

**GitHub Actions**: gate every PR, human or bot:

```yaml
# .github/workflows/proctor.yml
on: pull_request
permissions: { contents: read, pull-requests: write }
jobs:
  proctor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: nbn07/proctor@v0
        with:
          fail-on: high       # high | medium | low | none
          sarif: true         # optional: findings in the Security tab
```

You get a sticky PR comment, a job summary and an optional SARIF file for code scanning.

**pre-commit**:

```yaml
- repo: https://github.com/nbn07/proctor
  rev: v0.1.0
  hooks: [{ id: proctor }]
```

## Sometimes skipping a test is right

Waivers are allowed, but they stay visible. Put the reason on the line:

```python
@pytest.mark.skip(reason="upstream API down")  # proctor: allow P003 -- INC-4411, re-enable by Nov 1
```

A waived finding still shows up in every report with its reason, and a waived *high* finding turns the verdict to **WARN**, never a silent PASS. An agent can write a waiver, but it can't hide one from a reviewer. To ignore a rule entirely, or to protect your own graders and eval sets, use `.proctor.toml`. Proctor always reads its config from the **base** revision, so a change can't relax the rules it's being judged by:

```toml
fail_on = "high"
disable = ["P017"]
protect = ["evals/**", "scripts/grade.py"]   # any edit to these is a high finding
exclude = ["vendor/*"]
```

## Noise floor on real human commits

We ran `proctor scan` over the last 150 non-merge commits of six popular projects, all written by humans. The commits weren't cherry-picked and no rules were tuned per repo:

| Repo | Commits | PASS | WARN | FAIL |
|---|---:|---:|---:|---:|
| pallets/flask | 150 | 142 | 4 | 4 |
| psf/requests | 150 | 149 | 1 | 0 |
| encode/httpx | 150 | 137 | 6 | 7 |
| expressjs/express | 150 | 146 | 2 | 2 |
| pydantic/pydantic | 149 | 135 | 2 | 12 |
| vitejs/vite | 150 | 141 | 4 | 5 |
| **Total** | **899** | **94.5%** | **2.1%** | **3.3%** |

Every blocking finding on those commits came from four rules: a test file deleted, test cases removed, a skip/xfail added, or a CI test step removed. When a human does these things it's usually deliberate. When an agent does them halfway through "fix the failing test", you want a person to sign off. The heuristic rules (answer-key, result rewriting, exit forgery, test-aware code, always-equal, clock tampering) raised **zero** blocking findings across all 899 commits. Reproduce it with [`bench/false_positives.py`](bench/false_positives.py).

## Design principles

- **Deterministic.** Every finding points to a file, a line and the exact text that triggered it. You can disagree with a finding, but you can always see where it came from.
- **No LLM in the verdict.** An LLM judge can be argued with, prompt-injected or flattered. A regex can't.
- **No dependencies, fully offline.** Pure standard library on Python 3.11+ (`tomli` on older versions). Your code stays on your machine.
- **The referee is protected.** Changes to proctor's own config and hooks are findings too.
- **Honest about limits.** See the [threat model](docs/THREAT_MODEL.md). Proctor raises the cost of cheating a lot, but a determined adversary with shell access can still find a way around it.

## Related work

Proctor builds on, and is complementary to, research and tools such as [ImpossibleBench](https://arxiv.org/abs/2510.20270), METR's [reward-hacking report](https://metr.org/blog/2025-06-05-recent-reward-hacking), GSO's [HackDetector](https://gso-blog.notion.site/gso-hackdetector), [dotnet-slopwatch](https://www.nuget.org/packages/slopwatch.cmd) (.NET), [groundtruth](https://github.com/msal2020/groundtruth) (verifies an agent's claims) and [proof-of-work](https://pypi.org/project/proof-of-work-agent/). What proctor adds: **held-out exam mode**, **pristine-harness re-runs that measure harness inflation**, **answer-key detection from your own test data**, contamination checks, and one language-agnostic tool for Python, JS/TS, Go, Rust, Java, C# and Ruby.

## Roadmap

- **ProctorBench**: a public leaderboard of *generalization gap* per coding agent, measured on sealed exams.
- Mutation testing of the agent's diff, to catch tests that are present but hollow.
- AST-backed rules for Python and TypeScript, alongside the regex layer.
- A GitHub App that seals hidden tests server-side, so the agent never has them in the repo.
- VS Code / JetBrains gutter annotations.

## Contributing

Caught your agent cheating in a way proctor missed? **That's the most valuable contribution there is.** Add the diff to [`tests/fixtures/cheats/`](tests/fixtures/cheats/) with an `# expect: P0xx` header and open a PR, even without a fix. Every rule must also keep passing [`tests/fixtures/honest/`](tests/fixtures/honest/), the false-positive control set. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0 © Naveen Nair and contributors.
