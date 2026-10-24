"""proctor diff-test: old vs new behavior of changed Python functions."""

import os
import subprocess
import textwrap

import pytest

from proctor import difftest

ORIGINAL = '''
def to_roman(n):
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def clamp(x, lo, hi):
    return max(lo, min(x, hi))


def untouched(a):
    return a * 2
'''

TESTS = '''
from pkg.numerals import clamp, to_roman


def test_roman():
    assert to_roman(4) == "IV"
    assert to_roman(9) == "IX"
    assert to_roman(14) == "XIV"
    assert to_roman(1994) == "MCMXCIV"


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(15, 0, 10) == 10
'''


def sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, shell=True, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / "r")
    os.makedirs(os.path.join(r, "src", "pkg"))
    os.makedirs(os.path.join(r, "tests"))
    open(os.path.join(r, "src", "pkg", "__init__.py"), "w").close()
    open(os.path.join(r, "src", "pkg", "numerals.py"), "w").write(ORIGINAL)
    open(os.path.join(r, "tests", "test_numerals.py"), "w").write(TESTS)
    sh("git init -q && git config user.email t@t && git config user.name t && git add -A && git commit -qm init", r)
    return r


def rewrite(repo, old, new):
    p = os.path.join(repo, "src", "pkg", "numerals.py")
    src = open(p).read()
    assert old in src
    open(p, "w").write(src.replace(old, new))


LOOP = '''    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out'''


def test_honest_refactor_passes(repo):
    rewrite(repo, LOOP, '''    parts = []
    for v, s in vals:
        q = n // v if n > 0 else 0
        parts.append(s * q)
        n -= v * q
    return "".join(parts)''')
    res = difftest.diff_test(repo, samples=200)
    [f] = res.functions
    assert f.name == "to_roman" and f.status == "same" and f.agreed >= 50
    assert res.verdict == "PASS"


def test_subtle_edge_case_change_is_caught(repo):
    # Looks equivalent, passes every test, but divmod() treats negative numbers differently.
    rewrite(repo, LOOP, '''    parts = []
    for v, s in vals:
        q, n = divmod(n, v)
        parts.append(s * q)
    return "".join(parts)''')
    res = difftest.diff_test(repo, samples=200)
    [f] = res.functions
    assert f.status == "changed" and f.test_diverged == 0
    assert any(d["call"].startswith("to_roman(-") for d in f.diverged)
    assert "the tests can't see this" in difftest.text_report(res)


def test_behavior_change_is_reported_with_examples(repo):
    rewrite(repo, "return max(lo, min(x, hi))", "return max(lo, min(x, hi - 1))")
    res = difftest.diff_test(repo, samples=200)
    [f] = res.functions
    assert f.status == "changed" and f.test_diverged >= 1
    assert any(d["call"].startswith("clamp(") for d in f.diverged)
    assert res.verdict == "FAIL"


def test_fitted_to_tests_is_flagged_as_overfit(repo):
    # Matches the old code on exactly the values the tests use, and nothing else.
    rewrite(repo, '''    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out''', '''    table = dict([(4, "IV"), (9, "IX"), (14, "XIV"), (1994, "MCMXCIV")])
    return table.get(n, "I" * n)''')
    res = difftest.diff_test(repo, samples=200)
    [f] = res.functions
    assert f.test_inputs == 4 and f.test_diverged == 0
    assert f.status == "overfit" and len(f.diverged) > 10
    assert "fitted to the tests" in difftest.text_report(res)


def test_only_signature_preserving_changes_are_compared(repo):
    rewrite(repo, "def clamp(x, lo, hi):", "def clamp(x, lo, hi, strict=False):")
    assert difftest.diff_test(repo).functions == []


def test_input_generation_is_deterministic():
    t = difftest.Target("m.py", "f", ["text", "n"], {"n": "int"}, 0)
    a = difftest.generate(t, [(("abc", 3), {})], [], 50, seed=7)
    b = difftest.generate(t, [(("abc", 3), {})], [], 50, seed=7)
    assert a == b and a[0][2] == "test" and len(a) == 50
