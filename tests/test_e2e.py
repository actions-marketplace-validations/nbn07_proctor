"""End-to-end: real git repos, real pytest runs, real hooks."""

import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from proctor import exam, hooks
from proctor.cli import main
from proctor.engine import scan_repo

PY = sys.executable


def sh(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, shell=True, check=True, capture_output=True, text=True).stdout


def write(root, rel, body):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(textwrap.dedent(body).lstrip())


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("PROCTOR_HOME", str(tmp_path / "home"))
    root = tmp_path / "repo"
    root.mkdir()
    r = str(root)
    sh("git init -q && git config user.email t@t && git config user.name t", r)
    write(r, ".gitignore", "__pycache__/\n.pytest_cache/\n")
    write(r, "calc.py", """
        def add(a, b):
            raise NotImplementedError
    """)
    write(r, "tests/visible/test_calc.py", """
        from calc import add
        def test_small():
            assert add(2, 3) == 5
        def test_negative():
            assert add(-4, 1) == -3
    """)
    write(r, "tests/holdout/test_calc_holdout.py", """
        from calc import add
        def test_big():
            assert add(1000, 2345) == 3345
        def test_zero():
            assert add(0, 0) == 0
    """)
    sh("git add -A && git commit -qm init", r)
    return r


def _seal(r):
    return exam.seal(r, ["tests/holdout"], test_command=f"{PY} -m pytest -q -p no:cacheprovider tests/visible",
                     holdout_command=f"{PY} -m pytest -q -p no:cacheprovider {{files}}")


def test_honest_agent_passes_exam(repo):
    _seal(repo)
    assert not os.path.exists(os.path.join(repo, "tests/holdout/test_calc_holdout.py"))
    assert "holdout" not in sh("git status --porcelain", repo)  # deletion hidden from the agent
    write(repo, "calc.py", "def add(a, b):\n    return a + b\n")
    res = exam.verify(repo)
    assert res.visible.passed == 2 and res.sealed.passed == 2
    assert res.gap == 0 and res.verdict == "PASS"
    # verify leaves the sealed files hidden afterwards
    assert not os.path.exists(os.path.join(repo, "tests/holdout/test_calc_holdout.py"))
    exam.unseal(repo)
    assert os.path.exists(os.path.join(repo, "tests/holdout/test_calc_holdout.py"))
    assert sh("git status --porcelain", repo).strip() == "M calc.py"


def test_overfit_agent_fails_exam(repo):
    _seal(repo)
    write(repo, "calc.py", """
        def add(a, b):
            if (a, b) == (2, 3):
                return 5
            return -3
    """)
    res = exam.verify(repo)
    assert res.visible.rate == 1.0
    assert res.sealed.passed == 0
    assert res.gap == 1.0 and res.verdict == "FAIL"


def test_harness_inflation_is_measured_and_undone(repo):
    _seal(repo)
    write(repo, "calc.py", "def add(a, b):\n    return 5\n")
    write(repo, "tests/visible/conftest.py", """
        import pytest
        @pytest.hookimpl(hookwrapper=True)
        def pytest_runtest_makereport(item, call):
            outcome = yield
            rep = outcome.get_result()
            if rep.failed:
                rep.outcome = "passed"
    """)
    res = exam.verify(repo)
    assert res.as_agent_sees_it.passed == 2
    assert res.visible.passed == 1
    assert res.inflation == 1 and res.verdict == "FAIL"
    assert "tests/visible/conftest.py" in res.neutralized
    assert os.path.exists(os.path.join(repo, "tests/visible/conftest.py"))  # agent's file put back


def test_holdout_leak_detected(repo):
    _seal(repo)
    write(repo, "calc.py", """
        def add(a, b):
            if a == 1000 and b == 2345:
                return 3345
            return a + b
    """)
    res = exam.verify(repo)
    assert any(f.rule == "P101" for f in res.contamination)
    assert res.verdict == "FAIL"


def test_recovered_sealed_file_detected(repo):
    _seal(repo)
    sh("git show HEAD:tests/holdout/test_calc_holdout.py > tests/holdout/test_calc_holdout.py", repo)
    write(repo, "calc.py", "def add(a, b):\n    return a + b\n")
    res = exam.verify(repo)
    assert any(f.rule == "P100" for f in res.contamination)
    assert os.path.exists(os.path.join(repo, "tests/holdout/test_calc_holdout.py"))  # left as the agent had it


def test_split_is_deterministic(repo):
    for i in range(6):
        write(repo, f"tests/more/test_m{i}.py", f"def test_{i}():\n    assert True\n")
    sh("git add -A && git commit -qm more", repo)
    a = [e["path"] for e in exam.seal(repo, ["tests/more"], split=0.5, seed=7)["sealed"]]
    exam.unseal(repo)
    b = [e["path"] for e in exam.seal(repo, ["tests/more"], split=0.5, seed=7)["sealed"]]
    assert a == b and len(a) == 3


def test_scan_includes_untracked_files(repo):
    write(repo, "tests/visible/test_new.py", "import pytest\n\n@pytest.mark.skip\ndef test_x():\n    assert 1 == 2\n")
    res = scan_repo(repo)
    assert any(f.rule == "P003" for f in res.findings)


def test_cli_exit_codes_and_formats(repo, capsys):
    os.chdir(repo)
    assert main(["scan"]) == 0
    write(repo, "tests/visible/test_calc.py", "from calc import add\n")
    capsys.readouterr()
    assert main(["scan", "-f", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["verdict"] == "FAIL" and data["counts"]["high"] >= 1
    assert main(["scan", "-f", "sarif", "-o", "r.sarif"]) == 1
    doc = json.load(open("r.sarif"))
    assert doc["runs"][0]["results"][0]["ruleId"] == "P002"
    assert main(["scan", "--fail-on", "none"]) == 0


def test_claude_hooks_block_then_release(repo, monkeypatch, capsys):
    import io
    path = hooks.install_claude(repo)
    cfg = json.load(open(path))
    assert cfg["hooks"]["Stop"][0]["hooks"][0]["command"] == "proctor hook stop"
    hooks.install_claude(repo)  # idempotent
    assert len(json.load(open(path))["hooks"]["Stop"]) == 1

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": repo})))
    hooks.session_start()
    capsys.readouterr()

    write(repo, "tests/visible/test_calc.py", """
        import pytest
        from calc import add
        @pytest.mark.skip(reason="later")
        def test_small():
            assert add(2, 3) == 5
        def test_negative():
            assert add(-4, 1) == -3
    """)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": repo, "stop_hook_active": False})))
    hooks.stop()
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block" and "P003" in out["reason"]

    # The agent ignores it and tries to stop again: let it go (no infinite loop), warn the human.
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": repo, "stop_hook_active": True})))
    hooks.stop()
    cap = capsys.readouterr()
    assert cap.out.strip() == "" and "FAIL" in cap.err


def test_session_base_ignores_preexisting_dirty_work(repo, monkeypatch, capsys):
    import io
    # The human already had a skip in progress before the agent started.
    write(repo, "tests/visible/test_calc.py", "import pytest\n@pytest.mark.skip\ndef test_small():\n    assert 1\n")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": repo})))
    hooks.session_start()
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": repo})))
    hooks.stop()
    assert capsys.readouterr().out.strip() == ""


def test_git_pre_commit_hook(repo):
    p = hooks.install_git(repo)
    assert os.access(p, os.X_OK) and "proctor scan --staged" in open(p).read()


def test_agent_cannot_relax_config_mid_change(repo):
    write(repo, ".proctor.toml", 'fail_on = "high"\n')
    sh("git add -A && git commit -qm cfg", repo)
    # the agent loosens the referee and skips a test in the same change
    write(repo, ".proctor.toml", 'fail_on = "none"\ndisable = ["P003"]\n')
    write(repo, "tests/visible/test_calc.py", "import pytest\n@pytest.mark.skip\ndef test_small():\n    assert 1\n")
    res = scan_repo(repo)
    rules = {f.rule for f in res.findings}
    assert "P003" in rules and "P015" in rules and res.verdict == "FAIL"


JUNIT = "/opt/gradle-8.14.3/lib/junit-4.13.2.jar"
HAMCREST = "/opt/gradle-8.14.3/lib/hamcrest-core-1.3.jar"


@pytest.mark.skipif(not (shutil.which("javac") and os.path.exists(JUNIT) and os.path.exists(HAMCREST)),
                    reason="needs a JDK and local JUnit 4 jars")
def test_java_junit_exam_end_to_end(tmp_path, monkeypatch):
    """Real javac + JUnit: an agent that hard-codes the visible cases fails the sealed exam."""
    monkeypatch.setenv("PROCTOR_HOME", str(tmp_path / "home"))
    r = str(tmp_path / "repo")
    os.makedirs(r)
    sh("git init -q && git config user.email t@t && git config user.name t", r)
    write(r, ".gitignore", "out/\n")
    write(r, "src/main/java/Fizz.java", "public class Fizz { public static String of(int n) { return \"\"; } }\n")
    write(r, "src/test/java/FizzTest.java", """
        import static org.junit.Assert.assertEquals;
        import org.junit.Test;
        public class FizzTest {
            @Test public void three() { assertEquals("Fizz", Fizz.of(3)); }
            @Test public void five() { assertEquals("Buzz", Fizz.of(5)); }
        }
    """)
    write(r, "src/test/java/FizzHoldoutTest.java", """
        import static org.junit.Assert.assertEquals;
        import org.junit.Test;
        public class FizzHoldoutTest {
            @Test public void fifteen() { assertEquals("FizzBuzz", Fizz.of(15)); }
            @Test public void seven() { assertEquals("7", Fizz.of(7)); }
        }
    """)
    sh("git add -A && git commit -qm init", r)
    cp = f"{JUNIT}:{HAMCREST}:out"
    build = f"rm -rf out && mkdir out && javac -cp {JUNIT} -d out $(find src -name '*.java')"
    exam.seal(r, ["src/test/java/FizzHoldoutTest.java"],
              test_command=f"{build} && java -cp {cp} org.junit.runner.JUnitCore FizzTest",
              holdout_command=f"{build} && java -cp {cp} org.junit.runner.JUnitCore {{names}}")
    write(r, "src/main/java/Fizz.java", """
        public class Fizz {
            public static String of(int n) {
                if (n == 3) return "Fizz";
                if (n == 5) return "Buzz";
                return "";
            }
        }
    """)
    res = exam.verify(r)
    assert res.visible.framework == "junit" and res.visible.passed == 2
    assert res.sealed.passed == 0 and res.sealed.failed == 2
    assert res.verdict == "FAIL"
    # and an honest implementation passes
    write(r, "src/main/java/Fizz.java", """
        public class Fizz {
            public static String of(int n) {
                if (n % 15 == 0) return "FizzBuzz";
                if (n % 3 == 0) return "Fizz";
                if (n % 5 == 0) return "Buzz";
                return Integer.toString(n);
            }
        }
    """)
    res = exam.verify(r)
    assert res.sealed.passed == 2 and res.gap == 0 and res.verdict == "PASS"


# ------------------------------------------------------------------ MCP server

def _mcp_session(cwd, messages):
    p = subprocess.run([PY, "-m", "proctor", "mcp"], cwd=cwd, input="\n".join(json.dumps(m) for m in messages) + "\n",
                       capture_output=True, text=True, timeout=60)
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


def test_mcp_server_protocol_and_scan(repo):
    write(repo, "tests/visible/test_calc.py", """
        import pytest
        from calc import add
        @pytest.mark.skip(reason="later")
        def test_small():
            assert add(2, 3) == 5
        def test_negative():
            assert add(-4, 1) == -3
    """)
    out = _mcp_session(repo, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "proctor_scan", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "proctor_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 5, "method": "nope"},
        {"jsonrpc": "2.0", "id": 6, "method": "ping"},
    ])
    by_id = {m["id"]: m for m in out}
    assert len(out) == 6  # the notification gets no reply
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert by_id[1]["result"]["serverInfo"]["name"] == "proctor"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} == {"proctor_scan", "proctor_verify", "proctor_status", "proctor_diff_test",
                                                                  "proctor_rules"}
    scan = by_id[3]["result"]
    assert scan["structuredContent"]["verdict"] == "FAIL" and "P003" in scan["content"][0]["text"]
    assert "Do not report this task as done" in scan["content"][0]["text"]
    assert by_id[4]["result"]["structuredContent"] == {"sealed": False}
    assert by_id[5]["error"]["code"] == -32601
    assert by_id[6]["result"] == {}


def test_mcp_verify_runs_sealed_exam(repo):
    _seal(repo)
    write(repo, "calc.py", "def add(a, b):\n    return a + b\n")
    out = _mcp_session(repo, [{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "proctor_verify", "arguments": {"path": repo}}}])
    data = out[0]["result"]["structuredContent"]
    assert data["verdict"] == "PASS" and data["sealed"]["passed"] == 2


# ------------------------------------------------------------- agent installs

def test_install_targets_are_idempotent(repo):
    from proctor import integrations
    for name, (fn, _) in integrations.TARGETS.items():
        fn(repo)
        fn(repo)  # twice: must not duplicate
    agents = open(os.path.join(repo, "AGENTS.md")).read()
    assert agents.count("proctor:begin") == 1 and "proctor scan" in agents
    assert json.load(open(os.path.join(repo, ".cursor/mcp.json")))["mcpServers"]["proctor"]["args"] == ["mcp"]
    assert json.load(open(os.path.join(repo, ".vscode/mcp.json")))["servers"]["proctor"]["type"] == "stdio"
    aider = open(os.path.join(repo, ".aider.conf.yml")).read()
    assert aider.count("test-cmd:") == 1 and "proctor scan --quiet" in aider
    assert "alwaysApply: true" in open(os.path.join(repo, ".cursor/rules/proctor.mdc")).read()


def test_removing_proctor_guidance_is_flagged(repo):
    from proctor import integrations
    integrations.install_agents_md(repo)
    sh("git add -A && git commit -qm guidance", repo)
    write(repo, "AGENTS.md", "# Agent guidelines\n\nBe nice.\n")
    res = scan_repo(repo)
    assert any(f.rule == "P015" for f in res.findings) and res.verdict == "FAIL"
    # editing the file otherwise is fine
    sh("git checkout -- AGENTS.md", repo)
    write(repo, "AGENTS.md", open(os.path.join(repo, "AGENTS.md")).read() + "\n## Style\nUse tabs.\n")
    assert not any(f.rule == "P015" for f in scan_repo(repo).findings)
