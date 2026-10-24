# proctor diff-test

For refactors, the code before the change is the best possible test: it defines exactly what "unchanged behavior" means. `proctor diff-test` uses it.

```bash
proctor diff-test                          # compare the working tree with HEAD
proctor diff-test --base main              # compare a branch with main
proctor diff-test --function src/pkg/util.py::slugify --samples 1000
```

## What it compares

Every top-level Python function that the change modified **without changing its signature** (same parameter names and kinds). Functions whose signature changed, and new or deleted functions, aren't comparable and are skipped.

## Where the inputs come from

1. **Calls in your tests:** every call to the function with literal arguments, e.g. `slugify("Hello World")`. These are marked as *test inputs*.
2. **Calls elsewhere in your code**, the same way.
3. **Mutations** of those calls: off by one, zero, negated, doubled; empty, reversed, upper-cased and padded strings; shortened, reversed and extended lists.
4. **Type hints and parameter names** when there are no examples: `n: int` draws from boundary integers, `text` from tricky strings, `items` from lists.

All of it is seeded (`--seed`, default 0), so a run is reproducible.

## How it runs

The base revision is exported to a temporary directory. The old and new versions each run in their own Python subprocess, so the two copies of your package never share a process. Each call has a 2-second alarm. The comparison covers:

- the `repr()` of the return value (generators are drained up to 200 items);
- the exception type, if one is raised;
- in-place changes to the arguments.

The old version runs twice. Any input where it disagrees with itself (randomness, time, hash ordering) is dropped as nondeterministic, so it can't produce a false alarm.

## Reading the result

| Status | Meaning |
|---|---|
| ✓ **same** | identical behavior on every input tried |
| ✖ **changed** | at least one input behaves differently. If none of them is a test input, the report says *the tests can't see this* |
| ✖ **overfit** | identical on **every** input the tests use, different on **most** inputs they don't: the new code was fitted to the tests |
| ! **error** | a version couldn't be imported or run (missing dependency, import-time side effects) |

The verdict is **FAIL** on any *changed* or *overfit* function, so `proctor diff-test` exits 1. If the behavior change was intended, it wasn't a pure refactor, and the report shows you exactly what changed.

## On real history

Seven commits from [more-itertools](https://github.com/more-itertools/more-itertools) whose messages say *simplify*, *optimize* or *faster*:

| Commit | Message | diff-test |
|---|---|---|
| 0cfb9f5 | Micro-optimization for partition | PASS (283/283 same) |
| 237388c | Simplify and speed up nth_permutation | PASS (300/300) |
| 45a9b51 | itemgetter() is faster than a K combinator lambda | PASS (152/152) |
| fa3b62e | Simplify nth_combination with math.comb() | PASS (300/300) |
| 06f3181 | Simplify nth_combination_with_replacement. **Fix incorrect exception.** | FAIL: `ValueError` → results / `IndexError` |
| def2d82 | Simplify nth_permutation. **Fix incorrect exception.** | FAIL: `ValueError` → `IndexError` |
| 1b74b56 | **Fix**/simplify combination_with_replacement_index | FAIL: `0` → `TypeError` |

Every commit that claimed to be behavior-preserving passed. Every commit that also changed behavior on purpose was caught, with examples.

## Limits

- **Python only**, and top-level functions only (not methods).
- **The functions are executed**, just as your tests would execute them. Don't point it at code with destructive side effects.
- **Inputs are literals.** A function that only takes complex objects gets no examples from calls, only generated inputs.
