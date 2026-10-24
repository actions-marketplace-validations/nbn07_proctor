"""Scan orchestration, configuration and scoring."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from typing import List, Optional, Set

from . import diff as gitdiff
from .rules import (HIGH, LOW, MEDIUM, RULES, Context, Finding, harvest_test_literals, harvest_test_pairs,
                    run_rules, collect_test_texts)

try:  # Python 3.11+
    import tomllib as _toml
except ImportError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore
    except ImportError:
        _toml = None

WEIGHTS = {HIGH: 30, MEDIUM: 10, LOW: 2}
LEVELS = {"none": -1, "high": 0, "medium": 1, "low": 2}
SEV_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}


@dataclass
class Config:
    disable: Set[str] = field(default_factory=set)
    exclude: List[str] = field(default_factory=list)
    protect: List[str] = field(default_factory=list)
    fail_on: str = "high"
    test_command: Optional[str] = None
    holdout_command: Optional[str] = None
    min_holdout_pass: float = 1.0

    @classmethod
    def load(cls, root: Optional[str], rev: Optional[str] = None) -> "Config":
        """Load config from the working tree, or, when `rev` is given, from that commit.

        Scans read the config from the *base* revision: the change under review
        must not be able to rewrite the rules it is judged by.
        """
        cfg = cls()
        if not root or not _toml:
            return cfg

        def read(name: str) -> Optional[str]:
            if rev:
                return gitdiff.show_file(root, rev, name)
            p = os.path.join(root, name)
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh:
                    return fh.read()
            return None

        data = {}
        for name in (".proctor.toml", "proctor.toml"):
            text = read(name)
            if text is not None:
                try:
                    data = _toml.loads(text)
                except Exception:
                    data = {}
                break
        if not data:
            text = read("pyproject.toml")
            if text:
                try:
                    data = _toml.loads(text).get("tool", {}).get("proctor", {})
                except Exception:
                    data = {}
        cfg.disable = set(data.get("disable", []))
        cfg.exclude = list(data.get("exclude", []))
        cfg.protect = list(data.get("protect", []))
        cfg.fail_on = data.get("fail_on", cfg.fail_on)
        cfg.test_command = data.get("test_command")
        cfg.holdout_command = data.get("holdout_command")
        cfg.min_holdout_pass = float(data.get("min_holdout_pass", 1.0))
        return cfg


@dataclass
class ScanResult:
    findings: List[Finding]
    files_changed: int
    base: str
    score: int
    verdict: str  # PASS | WARN | FAIL

    @property
    def active(self) -> List[Finding]:
        return [f for f in self.findings if not f.waived]

    def counts(self) -> dict:
        c = {HIGH: 0, MEDIUM: 0, LOW: 0}
        for f in self.active:
            c[f.severity] += 1
        return c

    def to_dict(self) -> dict:
        return {
            "tool": "proctor", "base": self.base, "verdict": self.verdict, "integrity_score": self.score,
            "files_changed": self.files_changed, "counts": self.counts(),
            "findings": [f.to_dict() for f in self.findings],
        }


def score_and_verdict(findings: List[Finding], fail_on: str = "high"):
    active = [f for f in findings if not f.waived]
    penalty = sum(WEIGHTS[f.severity] for f in active)
    score = max(0, 100 - penalty)
    threshold = LEVELS.get(fail_on, 0)
    if any(SEV_RANK[f.severity] <= threshold for f in active):
        verdict = "FAIL"
    elif any(f.severity in (HIGH, MEDIUM) for f in active) or any(f.severity == HIGH for f in findings):
        # waived high-severity findings never pass silently: a waiver is a request for human review
        verdict = "WARN"
    else:
        verdict = "PASS"
    return score, verdict


def scan_text(diff_text: str, root: Optional[str] = None, base: str = "-", config: Optional[Config] = None) -> ScanResult:
    config = config or Config.load(root)
    files = gitdiff.parse_diff(diff_text)
    if config.exclude:
        files = [f for f in files if not any(fnmatch.fnmatch(f.path, g) for g in config.exclude)]
    tracked = gitdiff.tracked_files(root) if root else []
    ctx = Context(files=files, root=root, protect=config.protect)
    texts = collect_test_texts(root, files, tracked)
    ctx.test_literals = harvest_test_literals(texts, files)
    ctx.test_pairs = harvest_test_pairs(texts)
    findings = run_rules(ctx, config.disable)
    score, verdict = score_and_verdict(findings, config.fail_on)
    return ScanResult(findings, len(files), base, score, verdict)


def scan_repo(cwd: str, base: str = "HEAD", staged: bool = False, config: Optional[Config] = None) -> ScanResult:
    root = gitdiff.repo_root(cwd)
    text = gitdiff.collect_diff(root, base=base, staged=staged)
    if config is None:
        config = Config.load(root, rev="HEAD" if staged else base)
    return scan_text(text, root=root, base="index" if staged else base, config=config)


def rule_table() -> List[dict]:
    return [{"id": r.id, "slug": r.slug, "severity": r.severity, "title": r.title, "why": r.why} for r in RULES]
