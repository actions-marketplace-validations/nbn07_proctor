# Noise floor: proctor on human-written commits

**Setup.** `proctor 0.1.0`, default config (`fail_on = "high"`). For each repository, the latest 150 non-merge commits on the default branch as of 2026-10-24 were each scanned in diff-only mode against their first parent:

```bash
python bench/false_positives.py flask requests httpx express pydantic vite --commits 150
```

| Repo | Commits | PASS | WARN | FAIL | High findings by rule |
|---|---:|---:|---:|---:|---|
| pallets/flask | 150 | 142 | 4 | 4 | P002 ×4 |
| psf/requests | 150 | 149 | 1 | 0 | — |
| encode/httpx | 150 | 137 | 6 | 7 | P002 ×11, P001 ×1 |
| expressjs/express | 150 | 146 | 2 | 2 | P002 ×3 |
| pydantic/pydantic | 149 | 135 | 2 | 12 | P003 ×10, P007 ×4, P002 ×1, P001 ×1 |
| vitejs/vite | 150 | 141 | 4 | 5 | P002 ×10 |
| **Total** | **899** | **850 (94.5%)** | **19 (2.1%)** | **30 (3.3%)** | |

**Reading it.** Every high finding on these commits was literally what the rule says: a test file deleted (P001), test cases removed (P002), an unconditional skip/xfail added (P003), or a CI test step removed (P007). Skips gated on the Python version or platform are reported as *low*, not high. When humans make these changes they're usually deliberate. When an agent makes them while "fixing the failing test", they're what you most want to catch.

The heuristic rules (answer-key P011, result rewrite P008, exit forgery P009, test-aware code P010, always-equal P020, clock tampering P021) produced **no** high findings across all 899 commits.

**Caveat.** Diff-only mode can't see the full test suite, so the answer-key rule only knows the test literals that appear in each diff. In a real checkout it has more context. That raises recall and could slightly raise noise.
