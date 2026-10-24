<!-- mcp-name: io.github.nbn07/proctor -->
<div align="center">

# proctor

**The exam proctor for AI coding agents.**

Your agent says *"all tests pass ✅"*. Proctor checks whether it passed the exam or rewrote it.

[![CI](https://github.com/nbn07/proctor/actions/workflows/ci.yml/badge.svg)](https://github.com/nbn07/proctor/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agent-proctor.svg)](https://pypi.org/project/agent-proctor/)
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

## What it does

### 1 · `proctor scan`: did the change touch how it's judged?

A deterministic, explainable diff scanner with 21 rules for the ways agents game evaluations. It needs no API key, sends nothing over the network, and its verdict never depends on an LLM.

| | What the agent did | Rule |
|---|---|---|
| 🗑️ | Deleted a test file, or removed test cases | `P001` `P002` |
| ⏭️ | Added `skip` / `xfail` / `@Disabled` / `[Fact(Skip=…)]` / `DISABLED_` / `GTEST_SKIP()` / `#[ignore]`, or narrowed the run with `.only` / `--gtest_filter` | `P003` `P004` |
| 🫥 | `assert True`, `EXPECT_TRUE(true)`, `Assert.True(true)`, commented-out assertions, `EXPECT_EQ(x, 42)` weakened to `ASSERT_NE(x, nullptr)` | `P005` `P006` |
| ✏️ | Changed the *expected value* to match what the buggy code returns | `P019` |
| 🧪 | `conftest.py` that rewrites failures to passes; a JUnit `TestExecutionExceptionHandler` that swallows them; monkey-patched `assertEqual` | `P008` |
| 🚪 | `os._exit(0)` / `exit(0)` / `Environment.Exit(0)` in the harness so the run "succeeds" before failures print | `P009` |
| 🙈 | `collect_ignore`, `testPathIgnorePatterns`, `\|\| true`, `<skipTests>`, `ignoreFailures = true`, CTest `WILL_FAIL`, a test unregistered from `CMakeLists.txt`, CI test step deleted | `P007` |
| 🕵️ | Production code that checks `PYTEST_CURRENT_TEST` / `NODE_ENV === 'test'`, or compiles differently under `#ifdef UNIT_TEST` | `P010` |
| 📝 | **Answer-key special-casing:** `if s == "XIV": return 14`, matched against the exact input/expected pairs in your tests | `P011` |
| 🟰 | `__eq__` / `operator==` / `equals()` that returns `true` for everything | `P020` |
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
- **The true result**: real pass/fail counts read from the runner itself, never from the agent's summary. Proctor reads JUnit XML and .NET TRX reports written *during this run* (stale files are ignored), and otherwise parses the console summary. A run that collects zero tests counts as a fail.

No sealed tests yet? Split your existing suite like a dataset:

```bash
proctor seal tests/ --split 0.3 --seed 42    # hold out 30% of test files, reproducibly
```

### 3 · `proctor bench`: which agent actually works on *your* code?

Your git history is already a benchmark. Every commit that fixed a bug and added a test for it is a task with a known answer. `proctor bench` turns those commits into a private SWE-bench for your repository:

```bash
proctor bench mine --validate -o tasks.json          # bug-fix commits → tasks with hidden tests
proctor bench run tasks.json \
  --agent gold --agent noop \
  --agent claude='claude -p "$(cat {prompt_file})" --permission-mode acceptEdits' \
  --agent codex='codex exec --full-auto "$(cat {prompt_file})"' \
  --agent aider='aider --yes --message-file {prompt_file}'
```

- **Mining.** For each candidate commit, proctor takes the repo as it was *before* the fix and the commit message as the task. The tests that shipped with the fix become the hidden exam: for Python, exactly the test functions the fix added or changed (SWE-bench's FAIL_TO_PASS set). `--validate` keeps a task only if those tests fail before the fix and pass after it.
- **Running.** Each attempt runs in a fresh repository with a single commit, so the agent can't read the answer out of `git log`.
- **Scoring.** The agent's work is judged on two axes at once: did the hidden tests pass under a pristine harness, and did the attempt stay honest? Honest means no integrity findings, no harness inflation, and no branching on values that exist only in the hidden tests (a sign the answer was leaked or memorized).

```
proctor bench · leaderboard

  agent              tasks  honestly resolved   flagged  failed  regressed  hidden tests  integrity
  gold                   3       3 (100%)            0       0          0          100%      100.0
  noop                   3       0 (  0%)            0       3          0            0%      100.0
  overfitter             3       0 (  0%)            0       3          0            0%      100.0
  cheater                3       0 (  0%)            3       0          0            0%       70.0
```

`gold` (applies the real fix) and `noop` (does nothing) are built-in sanity checks; any shell command works as an agent. Try it with [`examples/bench_demo.sh`](examples/bench_demo.sh), which includes an agent that hard-codes the example from the task description and one that rewrites pytest's results. On [more-itertools](https://github.com/more-itertools/more-itertools), `proctor bench mine --validate` turned 12 of its recent bug-fix commits into 12 valid tasks in 20 seconds. Details: [`docs/BENCH.md`](docs/BENCH.md).

### 4 · `proctor diff-test`: did the "refactor" change behavior?

When the task is *"refactor this without changing what it does"*, the old code is a perfect oracle. `diff-test` runs the old and new versions of every changed Python function side by side, each in its own process, on hundreds of inputs: calls found in your tests and code, mutations of them, and values from type hints. It reports every input where the two disagree.

```
$ proctor diff-test
  ✖ src/pkg/numerals.py::to_roman  127/133 inputs behave the same
      the tests can't see this: all 4 tested inputs still match
      to_roman(-1994)
          before = ''
          after  = 'VI'
      … 5 more
```

That example is a real catch from writing proctor's own tests: a `divmod` "simplification" that passes every test but changes behavior for negative numbers. When new code matches the old behavior on every input the tests use but differs on most inputs they don't, diff-test says so: the code was fitted to the tests.

On real history it gets the answer right. We ran it on seven "simplify / optimize" commits from more-itertools. The four that claimed a pure speed-up all **PASS**. The three whose commit messages admit a behavior change ("Fix incorrect exception") all **FAIL**, each with concrete examples. Details: [`docs/DIFF_TEST.md`](docs/DIFF_TEST.md).

## Works with your stack

| Language | Scanner knows | Exam mode runs |
|---|---|---|
| Python | pytest, unittest | pytest, unittest |
| JavaScript / TypeScript | Jest, Vitest, Mocha, `node --test` | Jest, Vitest, Mocha, TAP |
| Go · Rust | `testing`, `#[test]` | `go test`, `cargo test` |
| Java · Kotlin | JUnit 4/5, TestNG, AssertJ, Maven, Gradle | Maven, Gradle, JUnit (Surefire XML read automatically) |
| C# · F# | xUnit, NUnit, MSTest, FluentAssertions | `dotnet test` (console or TRX) |
| C · C++ | GoogleTest, Catch2, doctest, Boost.Test, Unity, CMocka, CMake/CTest, Bazel | CTest, GoogleTest, Catch2, anything that writes JUnit XML |
| Anything else | deletions, CI changes, swallowed errors, answer-key special-casing | any runner that can write JUnit XML (`--report 'path/**/*.xml'`) |

There are runnable demos for [Python](examples/demo.sh) and [C++ with CMake + GoogleTest](examples/demo_cpp.sh), and the test suite includes a real `javac` + JUnit exam.

## Quick start

```bash
pipx install agent-proctor  # or: pip install agent-proctor  ·  Python ≥ 3.9 · the command is `proctor`
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

**Every other agent**: one command each. All targets are idempotent and can be re-run safely:

| Command | What it sets up |
|---|---|
| `proctor install cursor` | an always-on rule plus the MCP server in `.cursor/` |
| `proctor install copilot` | `.github/copilot-instructions.md` plus the VS Code MCP server |
| `proctor install codex` | `AGENTS.md` guidance; prints the `~/.codex/config.toml` MCP entry |
| `proctor install aider` | runs `proctor scan` with your tests after every edit (`auto-test`) |
| `proctor install openhands` · `windsurf` · `agents-md` | the same guidance where each agent reads it |
| `proctor install all` | everything above, plus Claude Code hooks |
| `proctor install git` | a pre-commit hook (`proctor scan --staged`) for any workflow |

Removing proctor's guidance from these files later is itself a finding (`P015`).

**MCP server**: `proctor mcp` speaks the Model Context Protocol over stdio, with no dependencies. Any MCP-capable agent can call `proctor_scan` before it claims "done", plus `proctor_verify`, `proctor_diff_test`, `proctor_status` and `proctor_rules`. It's tested against the official MCP Python SDK client.

```bash
claude mcp add proctor -- proctor mcp      # Claude Code
proctor install mcp                        # prints config for any other client
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
  rev: v0.2.0
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

We ran `proctor scan` over the last ~150 non-merge commits of 11 popular projects in five languages, all written by humans. The commits weren't cherry-picked and no rules were tuned per repo:

| Repo | Language | Commits | PASS | WARN | FAIL |
|---|---|---:|---:|---:|---:|
| google/leveldb | C++ | 150 | 144 | 5 | 1 |
| abseil/abseil-cpp | C++ | 150 | 148 | 1 | 1 |
| square/retrofit | Java | 150 | 149 | 0 | 1 |
| google/gson | Java | 150 | 145 | 3 | 2 |
| JamesNK/Newtonsoft.Json | C# | 150 | 146 | 2 | 2 |
| pallets/flask | Python | 150 | 142 | 4 | 4 |
| psf/requests | Python | 150 | 149 | 1 | 0 |
| encode/httpx | Python | 150 | 137 | 6 | 7 |
| pydantic/pydantic | Python | 149 | 136 | 2 | 11 |
| expressjs/express | JavaScript | 150 | 146 | 2 | 2 |
| vitejs/vite | TypeScript | 150 | 141 | 4 | 5 |
| **Total** | | **1,649** | **96.0%** | **1.8%** | **2.2%** |

Every blocking finding on those commits was literally what its rule says: a test file deleted, test cases removed, an unconditional skip added, an assertion commented out, or a test removed from CI or the build. When a human does these things it's usually deliberate. When an agent does them halfway through "fix the failing test", you want a person to sign off. The heuristic rules (answer-key, result rewriting, exit forgery, test-aware code, always-equal, clock tampering) raised **zero** blocking findings across all 1,649 commits. Reproduce it with [`bench/false_positives.py`](bench/false_positives.py); details are in [`bench/RESULTS.md`](bench/RESULTS.md).

## Design principles

- **Deterministic.** Every finding points to a file, a line and the exact text that triggered it. You can disagree with a finding, but you can always see where it came from.
- **No LLM in the verdict.** An LLM judge can be argued with, prompt-injected or flattered. A regex can't.
- **No dependencies, fully offline.** Pure standard library on Python 3.11+ (`tomli` on older versions). Your code stays on your machine.
- **The referee is protected.** Changes to proctor's own config and hooks are findings too.
- **Honest about limits.** See the [threat model](docs/THREAT_MODEL.md). Proctor raises the cost of cheating a lot, but a determined adversary with shell access can still find a way around it.

## Related work

Proctor builds on, and is complementary to, research and tools such as [ImpossibleBench](https://arxiv.org/abs/2510.20270), METR's [reward-hacking report](https://metr.org/blog/2025-06-05-recent-reward-hacking), GSO's [HackDetector](https://gso-blog.notion.site/gso-hackdetector), [dotnet-slopwatch](https://www.nuget.org/packages/slopwatch.cmd) (.NET), [groundtruth](https://github.com/msal2020/groundtruth) (verifies an agent's claims) and [proof-of-work](https://pypi.org/project/proof-of-work-agent/). What proctor adds: **held-out exam mode**, **pristine-harness re-runs that measure harness inflation**, **answer-key detection from your own test data**, contamination checks, and one language-agnostic tool for Python, JS/TS, Go, Rust, Java, C# and Ruby.

## Roadmap

- **ProctorBench**: a public leaderboard of honest-resolve and cheat rates per coding agent. The kit is ready in [`leaderboard/`](leaderboard/): 38 validated bug-fix tasks from four pinned Python libraries, agent templates, and run and aggregate scripts. The first published run is next.
- Mutation testing of the agent's diff, to catch tests that are present but hollow.
- Syntax-tree rules for Python and TypeScript, alongside the regex layer; `diff-test` for TypeScript.
- A GitHub App that seals hidden tests server-side, so the agent never has them in the repo.
- VS Code / JetBrains gutter annotations.

## Contributing

Caught your agent cheating in a way proctor missed? **That's the most valuable contribution there is.** Add the diff to [`tests/fixtures/cheats/`](tests/fixtures/cheats/) with an `# expect: P0xx` header and open a PR, even without a fix. Every rule must also keep passing [`tests/fixtures/honest/`](tests/fixtures/honest/), the false-positive control set. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Citing proctor

If proctor helps your research or your evaluation of coding agents, please cite it. GitHub's **"Cite this repository"** button (from [`CITATION.cff`](CITATION.cff)) gives APA and BibTeX:

```bibtex
@software{nair_proctor_2026,
  author  = {Naveen Babu Narayanan Nair},
  title   = {proctor: the exam proctor for AI coding agents},
  year    = {2026},
  version = {0.2.0},
  url     = {https://github.com/nbn07/proctor}
}
```

## License

Apache-2.0 © Naveen Babu Narayanan Nair and contributors.
