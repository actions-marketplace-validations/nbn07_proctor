"""Exam mode: a held-out test set for your coding agent.

Machine learning solved "the model memorised the benchmark" decades ago: you
keep a test set the model never sees. Coding agents are optimised against the
very tests that grade them, so Proctor brings the same discipline to software:

    proctor seal tests/holdout/     # hide some tests from the agent
    ... agent works against the visible tests ...
    proctor verify                  # re-run everything under a pristine harness
    proctor unseal                  # put the sealed tests back

`verify` reports the generalization gap: the difference between how well the
agent's code does on tests it could see and on tests it could not.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import classify
from . import diff as gitdiff
from .engine import Config, ScanResult, scan_repo
from .results import RunResult, run, with_files
from .rules import HIGH, Finding, _literals


class ExamError(RuntimeError):
    pass


def vault_dir(root: str) -> str:
    home = os.environ.get("PROCTOR_HOME") or os.path.join(os.path.expanduser("~"), ".proctor")
    key = hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]
    return os.path.join(home, "vaults", key)


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(root: str) -> str:
    return os.path.join(vault_dir(root), "manifest.json")


def load_manifest(root: str) -> Optional[dict]:
    p = _manifest_path(root)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def detect_test_command(root: str) -> str:
    j = lambda *p: os.path.exists(os.path.join(root, *p))
    if j("package.json"):
        try:
            with open(os.path.join(root, "package.json")) as fh:
                if "test" in json.load(fh).get("scripts", {}):
                    return "npm test --silent"
        except (OSError, ValueError):
            pass
    if j("go.mod"):
        return "go test -v ./..."
    if j("Cargo.toml"):
        return "cargo test"
    return "python -m pytest -q -p no:cacheprovider"


def _expand(root: str, paths: List[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        full = os.path.join(root, p)
        if os.path.isdir(full):
            for d, _, names in os.walk(full):
                for n in sorted(names):
                    rel = os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/")
                    if n == "__init__.py":
                        continue  # package markers stay; they reveal nothing
                    if classify.is_test(rel) or rel.endswith((".py", ".js", ".ts", ".go", ".rs", ".json")):
                        out.append(rel)
        elif os.path.isfile(full):
            out.append(os.path.relpath(full, root).replace(os.sep, "/"))
        else:
            raise ExamError(f"no such file or directory: {p}")
    return sorted(dict.fromkeys(out))


def seal(root: str, paths: List[str], split: Optional[float] = None, seed: Optional[int] = None,
         test_command: Optional[str] = None, holdout_command: Optional[str] = None) -> dict:
    if load_manifest(root):
        raise ExamError("an exam is already sealed for this repo; run `proctor unseal` first")
    files = _expand(root, paths)
    if split is not None:
        candidates = [f for f in files if classify.is_test(f)]
        if not candidates:
            raise ExamError("no test files found to split")
        k = max(1, round(len(candidates) * split))
        files = sorted(random.Random(seed).sample(candidates, k))
    if not files:
        raise ExamError("nothing to seal")
    vdir = vault_dir(root)
    os.makedirs(os.path.join(vdir, "files"), exist_ok=True)
    tracked = set(gitdiff.tracked_files(root))
    cfg = Config.load(root)
    try:
        base = gitdiff.git(["rev-parse", "HEAD"], root).strip()
    except gitdiff.GitError:
        base = None
    entries = []
    for rel in files:
        src = os.path.join(root, rel)
        dst = os.path.join(vdir, "files", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        entries.append({"path": rel, "sha256": _sha(src), "tracked": rel in tracked})
    manifest = {
        "version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "root": root,
        "base": base, "sealed": entries,
        "test_command": test_command or cfg.test_command or detect_test_command(root),
        "holdout_command": holdout_command or cfg.holdout_command,
    }
    with open(_manifest_path(root), "w") as fh:
        json.dump(manifest, fh, indent=2)
    for e in entries:
        os.remove(os.path.join(root, e["path"]))
        if e["tracked"]:
            # hide the deletion from `git status` so the agent doesn't helpfully restore it
            gitdiff.git(["update-index", "--skip-worktree", e["path"]], root, check=False)
    return manifest


def unseal(root: str) -> dict:
    m = load_manifest(root)
    if not m:
        raise ExamError("no sealed exam for this repo")
    vdir = vault_dir(root)
    for e in m["sealed"]:
        dst = os.path.join(root, e["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(vdir, "files", e["path"]), dst)
        if e["tracked"]:
            gitdiff.git(["update-index", "--no-skip-worktree", e["path"]], root, check=False)
    shutil.rmtree(vdir, ignore_errors=True)
    return m


@dataclass
class ExamResult:
    visible: RunResult
    sealed: RunResult
    as_agent_sees_it: Optional[RunResult]
    scan: Optional[ScanResult]
    contamination: List[Finding] = field(default_factory=list)
    neutralized: List[str] = field(default_factory=list)
    min_pass: float = 1.0

    @property
    def gap(self) -> Optional[float]:
        if self.visible.rate is None or self.sealed.rate is None:
            return None
        return round(self.visible.rate - self.sealed.rate, 4)

    @property
    def inflation(self) -> Optional[int]:
        """Extra passes the agent's harness edits bought, compared to the pristine harness."""
        if not self.as_agent_sees_it:
            return None
        return self.as_agent_sees_it.passed - self.visible.passed

    @property
    def verdict(self) -> str:
        if self.contamination or (self.scan and self.scan.verdict == "FAIL"):
            return "FAIL"
        if self.sealed.total == 0 or (self.sealed.rate or 0) < self.min_pass:
            return "FAIL"
        if self.inflation and self.inflation > 0:
            return "FAIL"
        if self.visible.failed or (self.scan and self.scan.verdict == "WARN"):
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict:
        return {
            "tool": "proctor", "mode": "exam", "verdict": self.verdict,
            "generalization_gap": self.gap, "harness_inflation": self.inflation,
            "visible": self.visible.to_dict(), "sealed": self.sealed.to_dict(),
            "as_agent_sees_it": self.as_agent_sees_it.to_dict() if self.as_agent_sees_it else None,
            "neutralized_harness_files": self.neutralized,
            "contamination": [f.to_dict() for f in self.contamination],
            "scan": self.scan.to_dict() if self.scan else None,
        }


def _contamination(root: str, m: dict, scan: Optional[ScanResult], diff_text: str) -> List[Finding]:
    out: List[Finding] = []
    vdir = vault_dir(root)
    for e in m["sealed"]:
        if os.path.exists(os.path.join(root, e["path"])):
            out.append(Finding("P100", "holdout-accessed", HIGH, "Sealed test file reappeared",
                               f"`{e['path']}` was sealed but is back in the working tree; the agent may have "
                               "recovered it from git.", e["path"]))
    # Literals that exist only in sealed tests and now show up in new source code = leaked answers.
    sealed_lits, visible_lits = set(), set()
    for e in m["sealed"]:
        with open(os.path.join(vdir, "files", e["path"]), encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                sealed_lits.update(_literals(line))
    for rel in gitdiff.tracked_files(root):
        if classify.is_test(rel) and not any(rel == e["path"] for e in m["sealed"]):
            try:
                with open(os.path.join(root, rel), encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        visible_lits.update(_literals(line))
            except OSError:
                pass
    secret = sealed_lits - visible_lits
    if secret:
        for f in gitdiff.parse_diff(diff_text):
            if not classify.is_source(f.path):
                continue
            for ln in f.added:
                hits = [x for x in _literals(ln.text) if x in secret]
                if hits:
                    out.append(Finding("P101", "holdout-leak", HIGH, "Sealed test values appear in the code",
                                       f"{', '.join(hits[:3])} appear only in sealed tests, yet the agent's code uses "
                                       "them verbatim.", f.path, ln.lineno, ln.text.strip()[:200]))
    return out


def _scrub_bytecode(root: str, rel: str) -> None:
    """Remove compiled copies of a sealed test so the agent can't decompile the exam afterwards."""
    d, name = os.path.split(os.path.join(root, rel))
    stem = os.path.splitext(name)[0]
    cache = os.path.join(d, "__pycache__")
    if os.path.isdir(cache):
        for n in os.listdir(cache):
            if n.startswith(stem + "."):
                try:
                    os.remove(os.path.join(cache, n))
                except OSError:
                    pass


def _harness_changes(root: str, base: Optional[str]) -> List[str]:
    if not base:
        return []
    names = gitdiff.git(["diff", "--name-only", base], root, check=False).split("\n")
    names += gitdiff.git(["ls-files", "--others", "--exclude-standard"], root, check=False).split("\n")
    return sorted({n for n in names if n and classify.is_harness(n)})


def verify(root: str, test_command: Optional[str] = None, holdout_command: Optional[str] = None,
           pristine: bool = True, timeout: int = 1800, run_scan: bool = True) -> ExamResult:
    m = load_manifest(root)
    if not m:
        raise ExamError("no sealed exam for this repo; run `proctor seal <tests>` first")
    base = m.get("base")
    cfg = Config.load(root, rev=base)
    vdir = vault_dir(root)
    tcmd = test_command or m["test_command"]
    sealed_paths = [e["path"] for e in m["sealed"]]
    hcmd = holdout_command or m.get("holdout_command") or with_files(tcmd, sealed_paths)
    if "{files}" in hcmd:
        hcmd = with_files(hcmd, sealed_paths)

    diff_text = gitdiff.collect_diff(root, base=base) if base else ""
    cfg.exclude = list(cfg.exclude) + sealed_paths  # sealed files are absent by design, not deleted
    scan = scan_repo(root, base=base, config=cfg) if (run_scan and base) else None
    contamination = _contamination(root, m, scan, diff_text)

    backup = os.path.join(vdir, "backup")
    shutil.rmtree(backup, ignore_errors=True)
    os.makedirs(backup, exist_ok=True)
    changed_harness = _harness_changes(root, base) if pristine else []
    agent_view: Optional[RunResult] = None
    placed: List[str] = []
    swapped: List[str] = []
    try:
        if changed_harness:
            agent_view = run(tcmd, root, timeout)
            for rel in changed_harness:
                cur = os.path.join(root, rel)
                if os.path.exists(cur):
                    os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
                    shutil.copy2(cur, os.path.join(backup, rel))
                original = gitdiff.show_file(root, base, rel)
                if original is None:
                    if os.path.exists(cur):
                        os.remove(cur)
                else:
                    with open(cur, "w", encoding="utf-8") as fh:
                        fh.write(original)
                swapped.append(rel)
        visible = run(tcmd, root, timeout)
        for e in m["sealed"]:
            dst = os.path.join(root, e["path"])
            if os.path.exists(dst):
                os.makedirs(os.path.dirname(os.path.join(backup, "__reappeared__", e["path"])), exist_ok=True)
                shutil.copy2(dst, os.path.join(backup, "__reappeared__", e["path"]))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(vdir, "files", e["path"]), dst)
            placed.append(e["path"])
        sealed = run(hcmd, root, timeout)
    finally:
        for rel in placed:
            _scrub_bytecode(root, rel)
            dst = os.path.join(root, rel)
            back = os.path.join(backup, "__reappeared__", rel)
            if os.path.exists(back):
                shutil.copy2(back, dst)
            elif os.path.exists(dst):
                os.remove(dst)
        for rel in swapped:
            cur, back = os.path.join(root, rel), os.path.join(backup, rel)
            if os.path.exists(back):
                shutil.copy2(back, cur)
            elif os.path.exists(cur):
                os.remove(cur)
        shutil.rmtree(backup, ignore_errors=True)
    return ExamResult(visible, sealed, agent_view, scan, contamination, swapped, cfg.min_holdout_pass)
