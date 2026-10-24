"""`proctor diff-test`: catch a refactor that changed behavior, with no tests to write.

When the task is "refactor this without changing what it does", the code
*before* the change is a perfect oracle. diff-test finds every Python function
the change modified, runs the old and new versions side by side, each in its
own subprocess, on hundreds of inputs, and reports every input where they
disagree.

Inputs come from three places, in this order:

1. calls to the function that already appear in your tests and code (`f(12, "a")`);
2. mutations of those calls (off-by-one, empty, negated, reversed, doubled…);
3. type hints and parameter names when there are no examples.

The sharpest signal is an asymmetry: if old and new agree on every input your
tests use but disagree on inputs the tests don't use, the new code was fitted
to the tests. Everything is deterministic (fixed seed) and nothing is judged by
an LLM.

Python only. The functions are executed, exactly as your test suite would
execute them, so run it on code you would run tests on.
"""

from __future__ import annotations

import ast
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import classify
from . import diff as gitdiff

# ------------------------------------------------------------------ harness (child)

HARNESS = r'''
import importlib, json, re, signal, sys, copy
req = json.loads(sys.stdin.read())
sys.path[:0] = req["paths"]
def dec(v):
    if isinstance(v, dict) and "__tuple__" in v: return tuple(dec(x) for x in v["__tuple__"])
    if isinstance(v, dict) and "__set__" in v: return set(dec(x) for x in v["__set__"])
    if isinstance(v, dict) and "__bytes__" in v: return bytes(v["__bytes__"])
    if isinstance(v, dict): return {k: dec(x) for k, x in v.items()}
    if isinstance(v, list): return [dec(x) for x in v]
    return v
def norm(s): return re.sub(r" at 0x[0-9a-fA-F]+", " at 0x?", s)
class Timeout(Exception): pass
def on_alarm(*_): raise Timeout()
if hasattr(signal, "SIGALRM"): signal.signal(signal.SIGALRM, on_alarm)
out = []
try:
    mod = importlib.import_module(req["module"])
    fn = getattr(mod, req["func"])
except BaseException as e:
    print(json.dumps({"import_error": f"{type(e).__name__}: {e}"}))
    raise SystemExit
for case in req["inputs"]:
    args, kwargs = dec(case["args"]), dec(case["kwargs"])
    try:
        if hasattr(signal, "SIGALRM"): signal.alarm(2)
        r = fn(*args, **kwargs)
        if hasattr(r, "__next__") and not isinstance(r, (str, bytes)):
            r = ("<iter>", list(__import__("itertools").islice(r, 200)))
        res = "= " + norm(repr(r))
        mut = norm(repr((args, kwargs)))  # in-place mutation of arguments is behavior too
        res += " | args→ " + mut
    except Timeout:
        res = "timeout"
    except BaseException as e:
        res = "raise " + type(e).__name__
    finally:
        if hasattr(signal, "SIGALRM"): signal.alarm(0)
    out.append(res[:2000])
print(json.dumps({"results": out}))
'''


def _enc(v: Any) -> Any:
    if isinstance(v, tuple):
        return {"__tuple__": [_enc(x) for x in v]}
    if isinstance(v, (set, frozenset)):
        return {"__set__": [_enc(x) for x in sorted(v, key=repr)]}
    if isinstance(v, bytes):
        return {"__bytes__": list(v)}
    if isinstance(v, dict):
        return {str(k): _enc(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    return v


# -------------------------------------------------------------------- discovery

@dataclass
class Target:
    path: str
    name: str
    params: List[str]
    annotations: Dict[str, str]
    defaults: int


def _functions(source: str) -> Dict[str, ast.FunctionDef]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("__")}


def _sig(fn: ast.FunctionDef) -> Tuple:
    a = fn.args
    return (tuple(x.arg for x in a.posonlyargs + a.args), a.vararg is not None, tuple(x.arg for x in a.kwonlyargs),
            a.kwarg is not None)


def changed_functions(root: str, base: str) -> List[Target]:
    names = gitdiff.git(["diff", "--name-only", base], root).split()
    out: List[Target] = []
    for rel in names:
        if not rel.endswith(".py") or not classify.is_source(rel):
            continue
        old_src = gitdiff.show_file(root, base, rel)
        path = os.path.join(root, rel)
        if old_src is None or not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            new_src = fh.read()
        old, new = _functions(old_src), _functions(new_src)
        for name, fn in new.items():
            if name not in old or _sig(old[name]) != _sig(fn):
                continue
            if ast.dump(old[name], include_attributes=False) == ast.dump(fn, include_attributes=False):
                continue
            a = fn.args
            params = [x.arg for x in a.posonlyargs + a.args]
            ann = {x.arg: ast.unparse(x.annotation) for x in a.posonlyargs + a.args if x.annotation is not None} \
                if hasattr(ast, "unparse") else {}
            out.append(Target(rel, name, params, ann, len(a.defaults)))
    return out


def parse_target(spec: str) -> Tuple[str, str]:
    path, _, name = spec.partition("::")
    if not name:
        raise ValueError(f"expected path.py::function, got {spec!r}")
    return path, name


# ---------------------------------------------------------------------- inputs

def _calls(source: str, name: str) -> List[Tuple[tuple, dict]]:
    found = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        callee = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if callee != name or any(isinstance(x, ast.Starred) for x in node.args):
            continue
        try:
            args = tuple(ast.literal_eval(x) for x in node.args)
            kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg}
        except (ValueError, SyntaxError, TypeError):
            continue
        if len(kwargs) != len(node.keywords):
            continue
        found.append((args, kwargs))
    return found


def harvest(root: str, name: str) -> Tuple[List, List]:
    """Literal-argument calls of `name` in test files (what the tests check) and elsewhere."""
    tests, other = [], []
    for rel in gitdiff.tracked_files(root):
        if not rel.endswith(".py"):
            continue
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="ignore") as fh:
                src = fh.read()
        except OSError:
            continue
        if name not in src:
            continue
        (tests if classify.is_test(rel) else other).extend(_calls(src, name))
    return tests, other


def _mutate(v: Any, rng: random.Random) -> List[Any]:
    if isinstance(v, bool):
        return [not v]
    if isinstance(v, int):
        return list(dict.fromkeys([v + 1, v - 1, -v, 0, v * 2, v * 10 + 7, abs(v) + rng.randint(2, 99)]))
    if isinstance(v, float):
        return [v + 0.5, -v, 0.0, v * 3, round(v, 1)]
    if isinstance(v, str):
        cands = ["", v.upper(), v.lower(), v[::-1], v + " x", v[1:], v * 2, " " + v + " ", v.replace(" ", "  ")]
        if v:
            i = rng.randrange(len(v))
            cands.append(v[:i] + rng.choice("aZ9 -_.") + v[i:])
        return list(dict.fromkeys(c for c in cands if c != v))
    if isinstance(v, (list, tuple)):
        t = type(v)
        cands = [t(), t(reversed(v)), t(list(v) + list(v[:1])), t(v[:1]), t(v[1:])]
        if v:
            i = rng.randrange(len(v))
            cands += [t(list(v[:i]) + [m] + list(v[i + 1:])) for m in _mutate(v[i], rng)[:3]]
        return [c for c in cands if c != v]
    if isinstance(v, dict):
        return [{}, {k: v[k] for k in list(v)[:1]}]
    return []


_POOLS = {
    "int": [0, 1, -1, 2, 3, 7, 10, 42, 100, -13, 999, 2 ** 31],
    "float": [0.0, 1.0, -1.5, 0.1, 3.14159, 1e9, -0.0],
    "str": ["", "a", "abc", "Hello World", "  spaced  ", "MiXeD 123", "ünïcödé", "a,b,c", "x" * 50],
    "bool": [True, False],
    "list": [[], [1], [3, 1, 2], [0, 0], [-5, 10, 7, 7], list(range(12))],
    "dict": [{}, {"a": 1}, {"a": 1, "b": 2}],
    "none": [None],
}


def _pool_for(param: str, ann: Optional[str]) -> List[Any]:
    a = (ann or "").lower()
    if "list[str]" in a or "sequence[str]" in a:
        return [[], ["a"], ["b", "a"], ["x", "", "y"]]
    if "list" in a or "sequence" in a or "iterable" in a:
        return _POOLS["list"]
    for key in ("bool", "int", "float", "str", "dict"):
        if re.search(rf"\b{key}\b", a):
            return _POOLS[key] + (_POOLS["none"] if "optional" in a or "none" in a else [])
    p = param.lower()
    if re.search(r"^(n|i|j|k|count|num|size|limit|index|idx|lo|hi|low|high|start|stop|step|width|depth|x|y)$", p):
        return _POOLS["int"]
    if re.search(r"(text|name|s|string|word|path|key|label|prefix|suffix|sep|title|msg|line)$", p):
        return _POOLS["str"]
    if re.search(r"(items|values|xs|nums|numbers|data|seq|lst|arr|elements)$", p):
        return _POOLS["list"]
    if re.search(r"^(is_|has_|allow|strict|flag|enable)", p):
        return _POOLS["bool"]
    return _POOLS["int"] + _POOLS["str"][:5]


def generate(t: Target, tests: List, other: List, n: int, seed: int) -> List[Tuple[tuple, dict, str]]:
    rng = random.Random(seed)
    seen, out = set(), []

    def add(args, kwargs, origin):
        key = repr((args, sorted(kwargs.items())))
        if key not in seen and len(out) < n:
            seen.add(key)
            out.append((tuple(args), dict(kwargs), origin))

    for a, k in tests:
        add(a, k, "test")
    for a, k in other:
        add(a, k, "example")
    examples = tests + other
    rounds = 0
    while examples and len(out) < n and rounds < n * 4:
        rounds += 1
        a, k = rng.choice(examples)
        a = list(a)
        if a and (not k or rng.random() < 0.7):
            i = rng.randrange(len(a))
            muts = _mutate(a[i], rng)
            if muts:
                a[i] = rng.choice(muts)
                add(a, k, "mutation")
        elif k:
            key = rng.choice(list(k))
            muts = _mutate(k[key], rng)
            if muts:
                add(a, {**k, key: rng.choice(muts)}, "mutation")
    required = t.params[: len(t.params) - t.defaults]
    if required and required[0] in ("self", "cls"):
        required = required[1:]
    pools = [_pool_for(p, t.annotations.get(p)) for p in required]
    tries = 0
    while len(out) < n and tries < n * 4:
        tries += 1
        add([rng.choice(pl) for pl in pools], {}, "generated")
    return out


# --------------------------------------------------------------------------- run

def _module_for(tree_root: str, rel: str) -> Tuple[str, str]:
    """(sys.path entry, dotted module name) for a file, honoring packages and src/ layouts."""
    parts = rel[:-3].split("/")
    i = len(parts) - 1
    while i > 0 and os.path.exists(os.path.join(tree_root, *parts[:i], "__init__.py")):
        i -= 1
    return os.path.join(tree_root, *parts[:i]), ".".join(parts[i:])


def _run_version(tree_root: str, t: Target, inputs: List, timeout: int) -> Dict:
    path_entry, module = _module_for(tree_root, t.path)
    req = {"paths": [path_entry, tree_root], "module": module, "func": t.name,
           "inputs": [{"args": _enc(list(a)), "kwargs": _enc(k)} for a, k, _ in inputs]}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    env.pop("PYTHONPATH", None)
    try:
        p = subprocess.run([sys.executable, "-c", HARNESS], input=json.dumps(req), cwd=tempfile.gettempdir(),
                           capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout}s"}
    lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
    if not lines:
        return {"error": (p.stderr.strip().splitlines() or ["no output"])[-1]}
    return json.loads(lines[-1])


def _export(root: str, rev: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    p = subprocess.Popen(["git", "archive", "--format=tar", rev], cwd=root, stdout=subprocess.PIPE)
    with tarfile.open(fileobj=p.stdout, mode="r|") as tar:
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)
    p.wait()


@dataclass
class FunctionReport:
    path: str
    name: str
    inputs: int = 0
    agreed: int = 0
    diverged: List[Dict] = field(default_factory=list)
    skipped_nondeterministic: int = 0
    test_inputs: int = 0
    test_diverged: int = 0
    error: str = ""

    @property
    def untested_divergence(self) -> float:
        untested = self.agreed + len(self.diverged) - self.test_inputs
        return (len(self.diverged) - self.test_diverged) / untested if untested > 0 else 0.0

    @property
    def overfit(self) -> bool:
        """Agrees with the old code on every input the tests use, but differs on most inputs they don't.

        A narrow slice of differences (an edge case) is reported as a behavior change instead.
        """
        return self.test_inputs > 0 and self.test_diverged == 0 and self.untested_divergence >= 0.5

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if not self.diverged:
            return "same"
        return "overfit" if self.overfit else "changed"


@dataclass
class DiffTestResult:
    base: str
    functions: List[FunctionReport]

    @property
    def verdict(self) -> str:
        if any(f.status == "overfit" for f in self.functions):
            return "FAIL"
        if any(f.status == "changed" for f in self.functions):
            return "FAIL"
        if any(f.status == "error" for f in self.functions):
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        return {"tool": "proctor", "mode": "diff-test", "base": self.base, "verdict": self.verdict,
                "functions": [dict(f.__dict__, status=f.status) for f in self.functions]}


def diff_test(root: str, base: str = "HEAD", targets: Optional[List[str]] = None, samples: int = 300,
              seed: int = 0, timeout: int = 120) -> DiffTestResult:
    root = gitdiff.repo_root(root)
    found = changed_functions(root, base)
    if targets:
        wanted = {parse_target(s) for s in targets}
        found = [t for t in found if (t.path, t.name) in wanted]
    tmp = tempfile.mkdtemp(prefix="proctor-difftest-")
    reports: List[FunctionReport] = []
    try:
        old_root = os.path.join(tmp, "base")
        _export(root, base, old_root)
        for t in found:
            rep = FunctionReport(t.path, t.name)
            tests, other = harvest(root, t.name)
            inputs = generate(t, tests, other, samples, seed)
            rep.inputs = len(inputs)
            old1 = _run_version(old_root, t, inputs, timeout)
            old2 = _run_version(old_root, t, inputs, timeout)
            new = _run_version(root, t, inputs, timeout)
            err = old1.get("import_error") or old1.get("error") or new.get("import_error") or new.get("error")
            if err:
                rep.error = err
                reports.append(rep)
                continue
            for (args, kwargs, origin), a, a2, b in zip(inputs, old1["results"], old2["results"], new["results"]):
                if a != a2 or a == "timeout":
                    rep.skipped_nondeterministic += 1
                    continue
                if origin == "test":
                    rep.test_inputs += 1
                if a == b:
                    rep.agreed += 1
                    continue
                if origin == "test":
                    rep.test_diverged += 1
                call = ", ".join([repr(x) for x in args] + [f"{k}={v!r}" for k, v in kwargs.items()])
                strip = lambda r: r.split(" | args→ ")[0]
                rep.diverged.append({"call": f"{t.name}({call})"[:300], "origin": origin,
                                     "before": strip(a)[:300], "after": strip(b)[:300]})
            reports.append(rep)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return DiffTestResult(base, reports)


# ------------------------------------------------------------------------ report

def text_report(res: DiffTestResult, limit: int = 5) -> str:
    out = [f"proctor diff-test · behavior of changed functions vs {res.base}", ""]
    if not res.functions:
        out.append("  No changed Python functions with an unchanged signature to compare.")
    icon = {"same": "✓", "changed": "✖", "overfit": "✖", "error": "!"}
    for f in res.functions:
        head = f"  {icon[f.status]} {f.path}::{f.name}"
        if f.status == "error":
            out.append(f"{head}  could not run: {f.error}")
            continue
        n = f.inputs - f.skipped_nondeterministic
        out.append(f"{head}  {f.agreed}/{n} inputs behave the same"
                   + (f"  ({f.skipped_nondeterministic} nondeterministic skipped)" if f.skipped_nondeterministic else ""))
        if f.status == "overfit":
            out.append(f"      matches the old behavior on all {f.test_inputs} inputs the tests use, but differs on "
                       f"{f.untested_divergence:.0%} of the others: fitted to the tests")
        elif f.status == "changed" and f.test_inputs and not f.test_diverged:
            out.append(f"      the tests can't see this: all {f.test_inputs} tested inputs still match")
        for d in f.diverged[:limit]:
            out.append(f"      {d['call']}")
            out.append(f"          before {d['before']}")
            out.append(f"          after  {d['after']}")
        if len(f.diverged) > limit:
            out.append(f"      … {len(f.diverged) - limit} more")
    out += ["", f"  {res.verdict}  " + {
        "PASS": "Every changed function behaves exactly as before on every input tried.",
        "WARN": "Some functions could not be exercised; see above.",
        "FAIL": "Behavior changed. If this was meant to be a pure refactor, it isn't."}[res.verdict]]
    return "\n".join(out)


def markdown_report(res: DiffTestResult) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[res.verdict]
    out = [f"### {icon} proctor diff-test: **{res.verdict}**", "", "| Function | Same | Diverged | Status |",
           "|---|---:|---:|---|"]
    for f in res.functions:
        out.append(f"| `{f.path}::{f.name}` | {f.agreed} | {len(f.diverged)} | {f.status} |")
    for f in res.functions:
        for d in f.diverged[:3]:
            out.append(f"- `{d['call']}`: before `{d['before']}`, after `{d['after']}`")
    return "\n".join(out)
