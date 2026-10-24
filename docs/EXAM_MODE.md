# Exam mode

Static rules catch the cheats we already know about. Exam mode catches the rest by measuring the result directly, the same way machine learning has measured overfitting for decades: **keep some tests the model never sees.**

## The loop

```bash
proctor seal tests/holdout/        # 1. hide held-out tests (before the agent starts)
#   2. the agent works, iterating against the tests it can see
proctor verify                     # 3. measure
proctor unseal                     # 4. restore
```

### What `seal` does

- Copies the files to a vault outside the repository (`~/.proctor/vaults/<repo-hash>/`, or `$PROCTOR_HOME`) and records each file's SHA-256 and the base commit.
- Deletes them from the working tree. If git tracks them, it also sets `--skip-worktree` so `git status` doesn't show the deletion. An agent that sees "deleted: tests/…" will often restore the files to be helpful.
- Leaves `__init__.py` package markers in place.
- Records the test commands: `--cmd` for the visible suite and `--holdout-cmd` for the sealed suite. `{files}` in the holdout command is replaced with the sealed paths.

`--split 0.3 --seed 42` picks 30% of the test files under the given paths at random, reproducibly, when you don't have a dedicated held-out set.

### What `verify` does

1. **Integrity scan** of everything that changed since the base commit (sealed paths excluded).
2. **Contamination check.** If a sealed file is back in the tree, the agent recovered it (`P100`). If literals that appear *only* in sealed tests show up in new source code, the agent saw the answers (`P101`).
3. **Agent-view run.** If the agent changed any harness file (`conftest.py`, `pytest.ini`, `pyproject.toml`, `package.json`, `jest.config.*`, CI files…), the visible suite is run once as the agent left it.
4. **Pristine run.** Those harness files are temporarily restored from the base commit, and agent-added harness files are moved aside. The visible suite runs again.
5. **Sealed run.** The sealed files are put back temporarily and the holdout command runs under the pristine harness.
6. **Cleanup** (in a `finally` block). The sealed files are removed again along with any compiled bytecode copies, and the agent's harness files are put back exactly as they were.

### Reading the report

| Signal | Meaning |
|---|---|
| **generalization gap** | visible pass rate − sealed pass rate. About 0 means the work generalizes. A large positive gap means the agent fit the visible tests. |
| **harness inflation** | passes under the agent's harness − passes under the pristine one. Anything above 0 means the agent's harness edits produced passes without fixing the code. |
| **sealed 0/0** | the holdout command collected nothing. This counts as a FAIL, because a sealed run with no tests proves nothing. |

Verdict: **FAIL** on contamination, a failing integrity scan, harness inflation, no sealed tests collected, or a sealed pass rate below `min_holdout_pass` (default `1.0`). **WARN** if visible tests fail or the scan warns. Otherwise **PASS**.

## Making the exam watertight

`seal` stops the agent from *stumbling onto* the held-out tests. It doesn't stop a determined agent with shell access from going looking for them. In order of strength:

1. **Untracked held-out tests.** Keep `tests/holdout/` in `.gitignore` and seal it. Then no copy exists in git history.
2. **Tests that never enter the agent's sandbox.** Keep the held-out suite in a separate private repository or CI secret, and run `proctor verify` in CI after the agent's branch is pushed. Use `--holdout-cmd` to point at the checkout.
3. **Run the agent in a container** that doesn't mount `~/.proctor`.

For pytest, keep `-p no:cacheprovider` in your commands (the default does this). Otherwise `.pytest_cache` records the node IDs of sealed tests.

## Runners

| Runner | Visible command | Holdout command |
|---|---|---|
| pytest | `python -m pytest -q -p no:cacheprovider tests/visible` | `python -m pytest -q -p no:cacheprovider {files}` |
| jest | `npx jest src` | `npx jest {files}` |
| vitest | `npx vitest run src` | `npx vitest run {files}` |
| go | `go test -v ./...` | `go test -v ./...` (the sealed `_test.go` files are present during the sealed run) |
| cargo | `cargo test` | `cargo test` (same) |

For go and cargo, which can't target individual files, the sealed run is the full suite with the sealed tests included.
