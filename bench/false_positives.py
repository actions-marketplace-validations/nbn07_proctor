"""Measure how often proctor complains about ordinary human commits.

    git clone --filter=blob:none https://github.com/pallets/flask /tmp/flask
    python bench/false_positives.py /tmp/flask --commits 300

Every commit is scanned in diff-only mode against its first parent. Human
commits do legitimately skip tests, bump snapshots and delete files, so this
is not a "zero is perfect" number; it is the noise floor a reviewer would see.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys

from proctor.engine import scan_text


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace").stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--commits", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    summary = []
    for repo in a.repos:
        shas = git(["rev-list", "--no-merges", f"--max-count={a.commits}", "HEAD"], repo).split()
        verdicts = collections.Counter()
        rules = collections.Counter()
        examples = collections.defaultdict(list)
        for sha in shas:
            text = git(["show", "--no-color", "-M", "--format=", sha], repo)
            if not text.strip():
                continue
            res = scan_text(text)
            verdicts[res.verdict] += 1
            for f in res.active:
                if f.severity == "high":
                    rules[f.rule] += 1
                    if len(examples[f.rule]) < 2:
                        examples[f.rule].append(f"{sha[:8]} {f.path}:{f.line} {f.snippet[:70]}")
        n = sum(verdicts.values())
        row = {"repo": repo, "commits": n, "PASS": verdicts["PASS"], "WARN": verdicts["WARN"],
               "FAIL": verdicts["FAIL"], "fail_rate": round(verdicts["FAIL"] / n, 4) if n else None,
               "high_by_rule": dict(rules.most_common()), "examples": examples}
        summary.append(row)
        if not a.json:
            print(f"{repo}: {n} commits · PASS {row['PASS']} · WARN {row['WARN']} · FAIL {row['FAIL']} "
                  f"({(row['fail_rate'] or 0) * 100:.1f}%)  {row['high_by_rule']}")
            for rule, ex in examples.items():
                for e in ex:
                    print(f"    {rule} {e}")
    if a.json:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
