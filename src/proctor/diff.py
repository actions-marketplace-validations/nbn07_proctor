"""Unified-diff parsing and git helpers.

Proctor works on *diffs*, not on whole trees: the question is never "is this
code good?" but "what did the agent change about how the code is judged?".
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Line:
    kind: str  # "+" or "-"
    text: str
    lineno: int  # new-file line for "+", old-file line for "-"
    hunk: int  # index of the hunk inside the file, for local pairing


@dataclass
class FileDiff:
    old_path: Optional[str]
    new_path: Optional[str]
    added: List[Line] = field(default_factory=list)
    removed: List[Line] = field(default_factory=list)
    context: List[Line] = field(default_factory=list)  # unchanged lines shown around the hunks
    is_new: bool = False
    is_deleted: bool = False
    is_rename: bool = False
    is_binary: bool = False

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    def hunks(self) -> Iterable[int]:
        return sorted({ln.hunk for ln in self.added} | {ln.hunk for ln in self.removed})

    def preceding(self, ln: Line, n: int = 2) -> List[str]:
        """Up to `n` non-blank lines just before an added line in the new file (added or context)."""
        new = {l.lineno: l.text for l in self.added + self.context}
        out, no = [], ln.lineno - 1
        while no > 0 and len(out) < n and no in new:
            if new[no].strip():
                out.append(new[no])
            no -= 1
        return out

    def in_hunk(self, idx: int):
        return ([l for l in self.removed if l.hunk == idx], [l for l in self.added if l.hunk == idx])


def _strip_prefix(p: str) -> Optional[str]:
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p == "/dev/null":
        return None
    if p[:2] in ("a/", "b/"):
        return p[2:]
    return p


def parse_diff(text: str) -> List[FileDiff]:
    """Parse `git diff` (or any unified diff) output into FileDiff objects."""
    files: List[FileDiff] = []
    cur: Optional[FileDiff] = None
    old_no = new_no = 0
    hunk_idx = -1

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            m = re.match(r'diff --git ("?a/.+?"?) ("?b/.+"?)$', raw)
            a, b = (m.group(1), m.group(2)) if m else ("", "")
            cur = FileDiff(old_path=_strip_prefix(a), new_path=_strip_prefix(b))
            files.append(cur)
            hunk_idx = -1
            continue
        if cur is None and (raw.startswith("--- ")):
            # plain unified diff without the git header
            cur = FileDiff(old_path=None, new_path=None)
            files.append(cur)
            hunk_idx = -1
        if cur is None:
            continue
        if raw.startswith("new file mode"):
            cur.is_new = True
        elif raw.startswith("deleted file mode"):
            cur.is_deleted = True
        elif raw.startswith("rename from "):
            cur.is_rename = True
            cur.old_path = raw[len("rename from "):]
        elif raw.startswith("rename to "):
            cur.is_rename = True
            cur.new_path = raw[len("rename to "):]
        elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            cur.is_binary = True
        elif raw.startswith("--- ") and hunk_idx == -1:
            p = _strip_prefix(raw[4:].split("\t")[0])
            cur.old_path = p
            if p is None:
                cur.is_new = True
        elif raw.startswith("+++ ") and hunk_idx == -1:
            p = _strip_prefix(raw[4:].split("\t")[0])
            cur.new_path = p
            if p is None:
                cur.is_deleted = True
        elif raw.startswith("@@"):
            m = _HUNK_RE.match(raw)
            if m:
                old_no, new_no = int(m.group(1)), int(m.group(3))
                hunk_idx += 1
        elif hunk_idx >= 0 and raw.startswith("+"):
            cur.added.append(Line("+", raw[1:], new_no, hunk_idx))
            new_no += 1
        elif hunk_idx >= 0 and raw.startswith("-"):
            cur.removed.append(Line("-", raw[1:], old_no, hunk_idx))
            old_no += 1
        elif hunk_idx >= 0 and raw.startswith(" "):
            cur.context.append(Line(" ", raw[1:], new_no, hunk_idx))
            old_no += 1
            new_no += 1
    return files


# --------------------------------------------------------------------------- git


class GitError(RuntimeError):
    pass


def git(args: List[str], cwd: str, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError as e:  # pragma: no cover - git missing
        raise GitError("git is not installed") from e
    if check and r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def repo_root(cwd: str) -> str:
    return git(["rev-parse", "--show-toplevel"], cwd).strip()


def _untracked_as_diff(cwd: str) -> str:
    out = git(["ls-files", "--others", "--exclude-standard", "-z"], cwd)
    chunks = []
    for path in filter(None, out.split("\0")):
        full = os.path.join(cwd, path)
        try:
            if os.path.getsize(full) > 2_000_000:
                continue
            with open(full, "r", encoding="utf-8") as fh:
                body = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        lines = body.splitlines()
        chunks.append(f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
                      f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{l}\n" for l in lines))
    return "".join(chunks)


def collect_diff(cwd: str, base: str = "HEAD", staged: bool = False,
                 include_untracked: bool = True) -> str:
    """Diff of everything that changed relative to `base` (working tree included)."""
    common = ["diff", "--no-color", "--no-ext-diff", "-M", "--unified=3"]
    if staged:
        return git(common + ["--cached"], cwd)
    text = git(common + [base], cwd)
    if include_untracked:
        text += _untracked_as_diff(cwd)
    return text


def show_file(cwd: str, rev: str, path: str) -> Optional[str]:
    r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=cwd, capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def tracked_files(cwd: str) -> List[str]:
    try:
        return [p for p in git(["ls-files", "-z"], cwd).split("\0") if p]
    except GitError:
        return []
