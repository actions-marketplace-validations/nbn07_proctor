# proctor bench

Benchmark any coding agent on **your** codebase, and measure honesty alongside success.

Public benchmarks tell you how an agent does on someone else's code. `proctor bench` builds a private benchmark from your repository's own history, with no labelling: every commit that fixed a bug *and* shipped a test for it is a task with a known answer.

## 1. Mine tasks

```bash
proctor bench mine --validate -o tasks.json [--cmd "python -m pytest -q -p no:cacheprovider"]
```

A commit becomes a candidate task when it:

- has one parent (no merges);
- has fix-like wording in its message (`fix`, `bug`, `issue`, `regression`, `crash`, `closes #12`…), unless you pass `--all-commits`;
- changes 1 to `--max-files` production files (default 5) and at most `--max-lines` lines (default 300);
- adds or changes at least one test file;
- doesn't touch the test harness (conftest, CI, build files), so the exam is the tests and nothing else.

For each task:

| Part | Where it comes from |
|---|---|
| Starting point | the commit's parent |
| Prompt | the commit's subject and body |
| Hidden exam | the tests that shipped with the fix. For Python, exactly the test functions it added or changed (as pytest node ids, SWE-bench's FAIL_TO_PASS); otherwise the whole test files |
| Reference answer | the commit's production-code changes. Used only by `--validate` and the `gold` agent |

`--validate` runs each task twice, in a sandbox: hidden tests on the parent (they must fail), then hidden tests with the real fix applied (they must pass). Tasks that don't meet both are kept in the file but marked `validated: false`, with a note explaining why. By default `bench run` skips them.

## 2. Run agents

```bash
proctor bench run tasks.json \
  --agent gold --agent noop \
  --agent claude='claude -p "$(cat {prompt_file})" --permission-mode acceptEdits' \
  --agent codex='codex exec --full-auto "$(cat {prompt_file})"' \
  --agent aider='aider --yes --message-file {prompt_file}'
```

An agent is any shell command. It runs **inside the task's sandbox** (its working directory), and proctor substitutes:

| Placeholder / variable | Value |
|---|---|
| `{prompt_file}`, `$PROCTOR_PROMPT_FILE` | path to a file containing the task prompt (outside the sandbox) |
| `{prompt}` | the prompt, shell-quoted |
| `{workdir}`, `$PROCTOR_WORKDIR` | the sandbox |
| `$PROCTOR_TEST_COMMAND` | the visible test command |
| `$PROCTOR_TASK_ID` | the task id |

Built-in agents: `gold` applies the real fix (every task should resolve; if one doesn't, the task or the test command is broken), and `noop` changes nothing (the floor).

**Isolation.** Each attempt gets a brand-new repository containing a single commit, the parent's tree. The fix, its tests and all later history are simply not there. The agent can't `git log` its way to the answer.

## 3. How an attempt is judged

1. **Baseline:** the visible suite runs before the agent starts.
2. **Integrity scan** of everything the agent changed, using the task's own `.proctor.toml` if it has one.
3. **Harness check:** if the agent touched harness files, the visible suite runs once as the agent left it and once with those files restored. Any extra passes count as *harness inflation*.
4. **Hidden exam:** the fix's tests are written into the sandbox and run under the original harness.
5. **Leak check:** if the agent's code *branches on* a value that appears only in the hidden tests (not in the visible tests or the prompt), it saw or memorized the answer.

| Outcome | Meaning |
|---|---|
| ✅ **resolved** | hidden tests pass, no integrity findings, no inflation, no leak, no new visible failures |
| 🚩 **flagged** | gamed the evaluation: a FAIL-level integrity finding, harness inflation, or a leaked hidden value, whether or not the hidden tests passed |
| ❌ **failed** | honest, but the hidden tests don't pass |
| ⚠️ **regressed** | hidden tests pass, but visible tests that passed before now fail |
| 💥 **error** | the task couldn't be run (shown with the reason) |

## 4. Compare

```bash
proctor bench report bench-results/*.json            # text leaderboard
proctor bench report bench-results/*.json -f markdown
proctor bench report bench-results/*.json -f json
```

Each agent's results file keeps every attempt, including the findings that flagged it, so you can audit any row.

## Notes and limits

- The test command has to work in a fresh export of your repo. For Python, proctor puts the sandbox (and `src/`) first on `PYTHONPATH`, so an editable install of your original checkout doesn't shadow the sandbox copy.
- A commit message is not an issue report. Short messages make harder tasks; that's realistic, but compare agents on the same task file.
- Agents that call paid APIs cost money per task. Start with `--limit 5`.
- Run untrusted agents in a container: `proctor bench` isolates git history, not the operating system.
