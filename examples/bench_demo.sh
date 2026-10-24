#!/usr/bin/env bash
# proctor bench in two minutes: mine tasks from a repo's own bug-fix history,
# then race four "agents" against them.
#
#   bash examples/bench_demo.sh      # needs: git, python3, pytest, proctor on PATH
set -euo pipefail
PROCTOR="${PROCTOR:-proctor}"
HERE="$(cd "$(dirname "$0")" && pwd)"
work="$(mktemp -d)"
cd "$work" && git init -q textkit && cd textkit
git config user.email dev@example.com && git config user.name dev
commit() { git add -A && git commit -qm "$1" ${2:+-m "$2"}; }

mkdir -p tests
cat > textkit.py <<'PY'
import re


def slugify(s):
    return "-".join(re.sub(r"[^a-z\s]", "", s.lower()).split())


def word_count(s):
    return len(s.split(" "))


def clamp(x, lo, hi):
    return max(lo, x)
PY
cat > tests/test_textkit.py <<'PY'
from textkit import clamp, slugify, word_count


def test_slugify_words():
    assert slugify("Hello World") == "hello-world"


def test_word_count():
    assert word_count("a b") == 2


def test_clamp_inside():
    assert clamp(5, 0, 10) == 5
PY
printf '__pycache__/\n.pytest_cache/\n' > .gitignore
commit "textkit: first version"

sed -i.bak 's/\[^a-z\\s\]/[^a-z0-9\\s]/' textkit.py && rm textkit.py.bak
cat >> tests/test_textkit.py <<'PY'


def test_slugify_keeps_digits():
    assert slugify("Top 10 Tips") == "top-10-tips"
    assert slugify("Python 3 rocks") == "python-3-rocks"
PY
commit "Fix slugify dropping digits" "e.g. slugify('Top 10 Tips') should be 'top-10-tips'."

sed -i.bak 's/len(s.split(" "))/len(s.split())/' textkit.py && rm textkit.py.bak
cat >> tests/test_textkit.py <<'PY'


def test_word_count_edge_cases():
    assert word_count("") == 0
    assert word_count("a   b") == 2
    assert word_count("  lead and trail  ") == 3
PY
commit "Fix word_count on empty strings and repeated spaces" "e.g. word_count('') should be 0."

sed -i.bak 's/return max(lo, x)/return max(lo, min(x, hi))/' textkit.py && rm textkit.py.bak
cat >> tests/test_textkit.py <<'PY'


def test_clamp_bounds():
    assert clamp(15, 0, 10) == 10
    assert clamp(-3, 0, 10) == 0
    assert clamp(99, 0, 50) == 50
PY
commit "Fix clamp ignoring the upper bound" "e.g. clamp(15, 0, 10) should be 10."

echo "# textkit" > README.md && commit "Add README"

CMD="python -m pytest -q -p no:cacheprovider"
echo "━━━ 1. Mine tasks from the repo's own bug-fix history ━━━"
$PROCTOR bench mine --validate --cmd "$CMD" -o tasks.json
echo
echo "━━━ 2. Race four agents (hidden tests = the tests that shipped with each fix) ━━━"
$PROCTOR bench run tasks.json --cmd "$CMD" --out results \
  --agent gold --agent noop \
  --agent overfitter="python3 $HERE/agents/overfitter.py" \
  --agent cheater="python3 $HERE/agents/cheater.py"
rm -rf "$work"
