"""Regenerate docs/RULES.md from the rule registry and the rogues' gallery.

    python scripts/gen_rules_doc.py > docs/RULES.md
"""
import glob
import os
import re

from proctor.engine import rule_table

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
examples = {}
for p in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "cheats", "*.diff"))):
    text = open(p, encoding="utf-8").read()
    for rid in re.search(r"# expect: (.+)", text).group(1).split(","):
        examples.setdefault(rid.strip(), []).append((os.path.basename(p), text))

print("# Rules\n")
print("Every rule is deterministic: a finding names the file, the line and the text that triggered it.")
print("Severity decides the verdict: any **high** finding fails the run by default (`fail_on = \"high\"`),")
print("**medium** findings produce WARN, **low** findings are informational.\n")
print("Waive a single occurrence with a reason on the same or previous line:\n")
print("```python\n@pytest.mark.skip(reason=\"vendor outage\")  # proctor: allow P003 -- INC-4411\n```\n")
print("| ID | Severity | Slug | Title |\n|---|---|---|---|")
for r in rule_table():
    print(f"| [{r['id']}](#{r['id'].lower()}) | {r['severity']} | `{r['slug']}` | {r['title']} |")
print("| P100 | high | `holdout-accessed` | Sealed test file reappeared (exam mode) |")
print("| P101 | high | `holdout-leak` | Values found only in sealed tests appear in the code (exam mode) |")
print()
for r in rule_table():
    print(f"## {r['id']}\n\n**{r['title']}** · `{r['slug']}` · severity: **{r['severity']}**\n\n{r['why']}\n")
    for name, text in examples.get(r["id"], [])[:1]:
        body = "\n".join(l for l in text.splitlines() if not l.startswith("# expect"))
        print(f"Example ([`{name}`](../tests/fixtures/cheats/{name})):\n\n```diff\n{body.strip()}\n```\n")
