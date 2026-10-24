# Noise floor: proctor on human-written commits

**Setup.** `proctor 0.1.0`, default config (`fail_on = "high"`). For each repository, the latest 150 non-merge commits on the default branch as of 2026-10-24 were each scanned in diff-only mode against their first parent:

```bash
python bench/false_positives.py leveldb abseil-cpp retrofit gson Newtonsoft.Json \
    flask requests httpx express pydantic vite --commits 150
```

| Repo | Language | Commits | PASS | WARN | FAIL | High findings by rule |
|---|---|---:|---:|---:|---:|---|
| google/leveldb | C++ | 150 | 144 | 5 | 1 | P007 ×1 (test removed from CMake) |
| abseil/abseil-cpp | C++ | 150 | 148 | 1 | 1 | P003 ×1 |
| square/retrofit | Java | 150 | 149 | 0 | 1 | P007 ×1, P001 ×1 |
| google/gson | Java | 150 | 145 | 3 | 2 | P002 ×1, P001 ×1 |
| JamesNK/Newtonsoft.Json | C# | 150 | 146 | 2 | 2 | P002 ×2, P006 ×1 (assertion commented out) |
| pallets/flask | Python | 150 | 142 | 4 | 4 | P002 ×4 |
| psf/requests | Python | 150 | 149 | 1 | 0 | — |
| encode/httpx | Python | 150 | 137 | 6 | 7 | P002 ×11, P001 ×1 |
| pydantic/pydantic | Python | 149 | 136 | 2 | 11 | P003 ×6, P007 ×4, P002 ×1, P001 ×1 |
| expressjs/express | JavaScript | 150 | 146 | 2 | 2 | P002 ×3 |
| vitejs/vite | TypeScript | 150 | 141 | 4 | 5 | P002 ×10 |
| **Total** | | **1,649** | **1,583 (96.0%)** | **30 (1.8%)** | **36 (2.2%)** | |

**Reading it.** Every high finding on these commits was literally what the rule says: a test file deleted (P001), test cases removed (P002), an unconditional skip/xfail added (P003), an assertion commented out (P006), or a test removed from CI or the build (P007). Skips that are gated on the platform, the language version or a runtime condition (`if (!supported) GTEST_SKIP()`) are reported as *low*, not high. When humans make these changes they're usually deliberate. When an agent makes them while "fixing the failing test", they're what you most want to catch.

The heuristic rules (answer-key P011, result rewrite P008, exit forgery P009, test-aware code P010, always-equal P020, clock tampering P021) produced **no** high findings across all 1,649 commits.

**Tuning history.** The first C++/Java/C# run blocked 46 commits (2.8%). We inspected every blocking finding. Fixing three over-broad patterns brought that down to 36 without losing any of the 43 cheats in the gallery: conditional `GTEST_SKIP()`, `maven.test.skip` being read as a JavaScript `test.skip`, and always-equal *test helper* types (now medium). The fixes and their honest-change fixtures are in the repo.

**Caveat.** Diff-only mode can't see the full test suite, so the answer-key rule only knows the test literals that appear in each diff. In a real checkout it has more context. That raises recall and could slightly raise noise.
