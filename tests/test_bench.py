"""proctor bench end to end: mine a repo's history, validate tasks, run agents, score them."""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from proctor import bench

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = os.path.join(os.path.dirname(HERE), "examples", "agents")
CMD = f"{sys.executable} -m pytest -q -p no:cacheprovider"


def sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, shell=True, check=True, capture_output=True, text=True)


def write(root, rel, body, append=False):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a" if append else "w") as fh:
        fh.write(textwrap.dedent(body).lstrip("\n"))


@pytest.fixture(scope="module")
def history(tmp_path_factory):
    r = str(tmp_path_factory.mktemp("hist") / "lib")
    os.makedirs(r)
    sh("git init -q && git config user.email t@t && git config user.name t", r)
    write(r, ".gitignore", "__pycache__/\n")
    write(r, "mathx.py", """
        def double(x):
            return x + x


        def sign(x):
            return 1 if x > 0 else -1
    """)
    write(r, "tests/test_mathx.py", """
        from mathx import double, sign


        def test_double():
            assert double(4) == 8


        def test_sign_positive():
            assert sign(7) == 1
    """)
    sh("git add -A && git commit -qm 'first version'", r)
    # a real bug fix with its test: the task
    write(r, "mathx.py", """
        def double(x):
            return x + x


        def sign(x):
            if x == 0:
                return 0
            return 1 if x > 0 else -1
    """)
    write(r, "tests/test_mathx.py", """


        def test_sign_zero_and_negative():
            assert sign(0) == 0
            assert sign(-9) == -1
    """, append=True)
    sh("git add -A && git commit -qm 'Fix sign(0) returning -1' -m \"e.g. sign(0) should be 0\"", r)
    # not a task: docs only
    write(r, "README.md", "# mathx\n")
    sh("git add -A && git commit -qm 'Add readme'", r)
    # not a task: a fix without a test
    write(r, "mathx.py", "# tidy\n", append=True)
    sh("git add -A && git commit -qm 'fix comment'", r)
    return r


def test_mine_finds_only_fix_commits_with_tests(history):
    tasks = bench.mine(history)
    assert [t.subject for t in tasks] == ["Fix sign(0) returning -1"]
    t = tasks[0]
    assert t.source_files == ["mathx.py"] and t.test_files == ["tests/test_mathx.py"]
    assert "sign(0) should be 0" in t.prompt


def test_validate_and_run_agents(history, tmp_path):
    tasks = bench.mine(history)
    bench.validate(history, tasks[0], CMD)
    assert tasks[0].validated and tasks[0].fail_before >= 1 and tasks[0].pass_after >= 1
    tf = str(tmp_path / "tasks.json")
    bench.save_tasks(tf, history, tasks, CMD)

    files = bench.run_bench(tf, ["gold", "noop",
                                 f"overfitter={sys.executable} {AGENTS}/overfitter.py",
                                 f"cheater={sys.executable} {AGENTS}/cheater.py"],
                            out_dir=str(tmp_path / "out"))
    rows = {r["agent"]: r for r in bench.summarize(files)}
    assert rows["gold"]["resolved"] == 1 and rows["gold"]["flagged"] == 0
    assert rows["noop"]["resolved"] == 0 and rows["noop"]["failed"] == 1
    # hard-coding the example from the prompt passes one hidden assert, not the other
    assert rows["overfitter"]["resolved"] == 0
    # rewriting pytest results is flagged, and the hidden tests still run under the real harness
    assert rows["cheater"]["flagged"] == 1 and rows["cheater"]["resolved_any"] == 0
    md = bench.report_markdown(list(rows.values()))
    assert "| gold | 1 | 1 (100%)" in md

    # the sandbox exposes no future history to the agent
    doc = json.load(open(files[0]))
    assert doc["attempts"][0]["files_changed"] == 1


def test_sandbox_has_no_future_history(history, tmp_path):
    t = bench.mine(history)[0]
    d = bench.export(history, t.parent, str(tmp_path / "sb"))
    log = subprocess.run(["git", "log", "--all", "--oneline"], cwd=d, capture_output=True, text=True).stdout
    assert len(log.strip().splitlines()) == 1
    assert "sign(0) == 0" not in open(os.path.join(d, "tests/test_mathx.py")).read()


def test_parse_agent():
    assert bench.parse_agent("gold") == ("gold", "gold")
    assert bench.parse_agent("claude=claude -p x") == ("claude", "claude -p x")
    assert bench.parse_agent("aider --yes") == ("aider", "aider --yes")


def test_agent_that_commits_is_still_judged(history, tmp_path):
    """Agents like aider commit their edits; judging must compare against the sandbox's first commit."""
    tasks = bench.mine(history)
    bench.validate(history, tasks[0], CMD)
    tf = str(tmp_path / "tasks.json")
    bench.save_tasks(tf, history, tasks, CMD)
    committing_cheater = (f"{sys.executable} {AGENTS}/cheater.py && git add -A && "
                          "git -c user.name=a -c user.email=a@a commit -qm 'agent work'")
    files = bench.run_bench(tf, [f"committer={committing_cheater}"], out_dir=str(tmp_path / "out"))
    [row] = bench.summarize(files)
    assert row["flagged"] == 1
