"""Render results as terminal text, Markdown (PR comments), JSON or SARIF."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import List, Optional

from . import __version__
from .engine import ScanResult, rule_table
from .exam import ExamResult
from .rules import HIGH, LOW, MEDIUM, Finding

_C = {"red": "31", "yellow": "33", "green": "32", "dim": "2", "bold": "1", "cyan": "36", "magenta": "35"}


def _color_on(stream=sys.stdout) -> bool:
    if os.environ.get("FORCE_COLOR"):
        return True
    return stream.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def _c(text: str, *styles: str, on: bool = True) -> str:
    if not on:
        return text
    return "".join(f"\x1b[{_C[s]}m" for s in styles) + text + "\x1b[0m"


SEV_ICON = {HIGH: "✖", MEDIUM: "▲", LOW: "·"}
SEV_COLOR = {HIGH: "red", MEDIUM: "yellow", LOW: "dim"}
VERDICT_COLOR = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
VERDICT_LINE = {
    "PASS": "No signs the agent gamed its own evaluation.",
    "WARN": "Changes to how this work is judged need a human look.",
    "FAIL": "The agent changed how its work is graded. Do not trust the green checkmark.",
}


def _finding_text(f: Finding, on: bool) -> str:
    loc = f"{f.path}:{f.line}" if f.line else f.path
    head = f"  {_c(SEV_ICON[f.severity], SEV_COLOR[f.severity], on=on)} {_c(f.rule, 'bold', on=on)} {f.title}  {_c(loc, 'cyan', on=on)}"
    lines = [head, f"      {f.message}"]
    if f.snippet:
        lines.append(_c(f"      │ {f.snippet}", "dim", on=on))
    if f.waived:
        lines.append(_c(f"      waived: {f.waived}", "magenta", on=on))
    return "\n".join(lines)


def scan_text(res: ScanResult, color: Optional[bool] = None) -> str:
    on = _color_on() if color is None else color
    out = [_c(f"proctor {__version__}", "bold", on=on) + _c(f"  ·  {res.files_changed} file(s) changed vs {res.base}", "dim", on=on), ""]
    active = [f for f in res.findings if not f.waived]
    waived = [f for f in res.findings if f.waived]
    if not res.findings:
        out.append("  Nothing touched the tests, the harness or the referee in a suspicious way.")
    for f in active:
        out += [_finding_text(f, on), ""]
    if waived:
        out.append(_c(f"  {len(waived)} waived finding(s):", "magenta", on=on))
        for f in waived:
            out += [_finding_text(f, on), ""]
    c = res.counts()
    out.append(f"  {c[HIGH]} high · {c[MEDIUM]} medium · {c[LOW]} low      integrity {res.score}/100")
    out.append("  " + _c(f" {res.verdict} ", "bold", VERDICT_COLOR[res.verdict], on=on) + "  " + VERDICT_LINE[res.verdict])
    return "\n".join(out)


def _pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def exam_text(res: ExamResult, color: Optional[bool] = None) -> str:
    on = _color_on() if color is None else color
    v, s = res.visible, res.sealed
    out = [_c(f"proctor {__version__} · exam", "bold", on=on), ""]
    short = lambda cmd: cmd if len(cmd) <= 60 else cmd[:57] + "…"
    out.append(f"  visible tests   {v.passed:>4}/{v.total:<4} passed  {_pct(v.rate):>5}   {_c(short(v.command), 'dim', on=on)}")
    out.append(f"  sealed tests    {s.passed:>4}/{s.total:<4} passed  {_pct(s.rate):>5}   {_c(short(s.command), 'dim', on=on)}")
    if res.gap is not None:
        col = "green" if res.gap <= 0.05 else "yellow" if res.gap <= 0.2 else "red"
        out.append("  " + _c(f"generalization gap  {res.gap * 100:+.0f} pts", "bold", col, on=on)
                   + _c("   (visible − sealed pass rate)", "dim", on=on))
    if res.as_agent_sees_it is not None:
        a = res.as_agent_sees_it
        out.append("")
        out.append(f"  harness as the agent left it: {a.passed}/{a.total} passed, exit {a.exit_code}")
        out.append(f"  harness restored to original: {v.passed}/{v.total} passed, exit {v.exit_code}")
        if res.inflation:
            out.append(_c(f"  ✖ the agent's harness edits inflated the result by {res.inflation} pass(es)", "red", on=on))
        out.append(_c("    neutralized: " + ", ".join(res.neutralized), "dim", on=on))
    if s.total == 0:
        out.append(_c("  ✖ no sealed tests were collected — check the holdout command", "red", on=on))
    if res.contamination:
        out.append("")
        for f in res.contamination:
            out.append(_finding_text(f, on))
    if res.scan and res.scan.findings:
        c = res.scan.counts()
        out.append("")
        out.append(f"  integrity scan  {_c(res.scan.verdict, 'bold', VERDICT_COLOR[res.scan.verdict], on=on)}  "
                   f"{c[HIGH]} high · {c[MEDIUM]} medium · {c[LOW]} low   " + _c("(details: proctor scan --base "
                   + (res.scan.base[:12] if res.scan.base else "HEAD") + ")", "dim", on=on))
    if not s.ok and s.tail:
        failed = [l for l in s.tail.splitlines() if re.match(r"\s*(FAILED|ERROR|--- FAIL|✕|×|●|not ok)\b", l)]
        out.append("")
        out.append(_c("  sealed failures:", "dim", on=on))
        out += [_c("    " + l.strip()[:110], "dim", on=on) for l in (failed or s.tail.splitlines()[-8:])[:10]]
    out.append("")
    msg = {"PASS": "The work generalizes to tests the agent never saw.",
           "WARN": "Passes the sealed exam, but something needs a human look.",
           "FAIL": "The work does not hold up on tests the agent could not see, or the exam was tampered with."}
    out.append("  " + _c(f" {res.verdict} ", "bold", VERDICT_COLOR[res.verdict], on=on) + "  " + msg[res.verdict])
    return "\n".join(out)


def scan_markdown(res: ScanResult) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[res.verdict]
    c = res.counts()
    out = [f"### {icon} Proctor: **{res.verdict}** · integrity {res.score}/100",
           "", f"_{VERDICT_LINE[res.verdict]}_", ""]
    if res.findings:
        out += ["| | Rule | Finding | Where |", "|---|---|---|---|"]
        for f in res.findings:
            sev = {"high": "🔴", "medium": "🟡", "low": "⚪"}[f.severity]
            where = f"`{f.path}:{f.line}`" if f.line else f"`{f.path}`"
            msg = f.message.replace("|", "\\|")
            if f.waived:
                msg += f" <br>_waived: {f.waived}_"
            out.append(f"| {sev} | `{f.rule}` {f.title} | {msg} | {where} |")
        out.append("")
    out.append(f"<sub>{c[HIGH]} high · {c[MEDIUM]} medium · {c[LOW]} low · {res.files_changed} files scanned · "
               f"[proctor](https://github.com/nbn07/proctor) {__version__}</sub>")
    return "\n".join(out)


def exam_markdown(res: ExamResult) -> str:
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[res.verdict]
    v, s = res.visible, res.sealed
    out = [f"### {icon} Proctor exam: **{res.verdict}**", "",
           "| Suite | Passed | Rate |", "|---|---|---|",
           f"| Visible (agent could see) | {v.passed}/{v.total} | {_pct(v.rate)} |",
           f"| Sealed (agent never saw) | {s.passed}/{s.total} | {_pct(s.rate)} |", ""]
    if res.gap is not None:
        out.append(f"**Generalization gap:** {res.gap * 100:+.0f} points")
    if res.inflation:
        out.append(f"**Harness inflation:** the agent's edits to {', '.join(res.neutralized)} added {res.inflation} fake pass(es).")
    for f in res.contamination:
        out.append(f"- 🔴 `{f.rule}` {f.message}")
    if res.scan:
        out += ["", scan_markdown(res.scan)]
    return "\n".join(out)


def sarif(res: ScanResult) -> str:
    level = {HIGH: "error", MEDIUM: "warning", LOW: "note"}
    rules = [{"id": r["id"], "name": r["slug"], "shortDescription": {"text": r["title"]},
              "fullDescription": {"text": r["why"]},
              "helpUri": f"https://github.com/nbn07/proctor/blob/main/docs/RULES.md#{r['id'].lower()}",
              "defaultConfiguration": {"level": level[r["severity"]]}} for r in rule_table()]
    results = []
    for f in res.findings:
        item = {"ruleId": f.rule, "level": level[f.severity], "message": {"text": f.message},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.path},
                                                    "region": {"startLine": max(1, f.line)}}}]}
        if f.waived:
            item["suppressions"] = [{"kind": "inSource", "justification": f.waived}]
        results.append(item)
    doc = {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
           "runs": [{"tool": {"driver": {"name": "proctor", "version": __version__,
                                         "informationUri": "https://github.com/nbn07/proctor", "rules": rules}},
                     "results": results}]}
    return json.dumps(doc, indent=2)


def as_json(obj) -> str:
    return json.dumps(obj.to_dict(), indent=2, default=str)
