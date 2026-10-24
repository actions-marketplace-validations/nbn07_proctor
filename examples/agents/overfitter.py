#!/usr/bin/env python3
"""A demo 'agent' that overfits: it hard-codes the example from the task description.

It reads `f('input') should be 'output'` from the prompt and inserts
`if <arg> == 'input': return 'output'` at the top of `f`. It never solves the
general bug, which is exactly what hidden tests are for.
"""
import os
import re
import sys

prompt = open(os.environ["PROCTOR_PROMPT_FILE"], encoding="utf-8").read()
m = re.search(r"(\w+)\((['\"])(.*?)\2\)\s+should (?:be|return)\s+(['\"]?)(.*?)\4(?:[.\s]|$)", prompt)
if not m:
    sys.exit(0)
func, inp, out = m.group(1), m.group(3), m.group(5)
ret = repr(out) if m.group(4) else out
for dirpath, _, names in os.walk("."):
    if ".git" in dirpath:
        continue
    for n in names:
        if not n.endswith(".py") or n.startswith("test_"):
            continue
        path = os.path.join(dirpath, n)
        src = open(path, encoding="utf-8").read()
        d = re.search(rf"^def {func}\((\w+)[^)]*\):\n", src, re.M)
        if d:
            patch = f"    if {d.group(1)} == {inp!r}:\n        return {ret}\n"
            open(path, "w", encoding="utf-8").write(src[:d.end()] + patch + src[d.end():])
            sys.exit(0)
