from proctor import classify
from proctor.diff import parse_diff
from proctor.engine import Config, scan_text
from proctor.rules import RULES, _literals


def mk(path, added=(), removed=(), new=False):
    head = f"diff --git a/{path} b/{path}\n"
    head += "new file mode 100644\n--- /dev/null\n" if new else f"--- a/{path}\n"
    head += f"+++ b/{path}\n@@ -1,{len(removed)} +1,{len(added)} @@\n"
    return head + "".join(f"-{l}\n" for l in removed) + "".join(f"+{l}\n" for l in added)


def rules_of(text, **kw):
    return {f.rule for f in scan_text(text, **kw).findings}


def test_rule_ids_unique_and_documented():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
    for r in RULES:
        assert r.title and r.why and r.severity in ("high", "medium", "low")


def test_parse_diff_handles_new_deleted_and_renamed():
    text = mk("a.py", ["x = 1"], new=True) + "diff --git a/b.py b/c.py\nsimilarity index 100%\nrename from b.py\nrename to c.py\n"
    files = parse_diff(text)
    assert files[0].is_new and files[0].added[0].text == "x = 1"
    assert files[1].is_rename and files[1].path == "c.py" and files[1].old_path == "b.py"


def test_classify_roles():
    assert classify.role("tests/test_x.py") == "test"
    assert classify.role("src/foo.test.ts") == "test"
    assert classify.role("pkg/foo_test.go") == "test"
    assert classify.role("tests/conftest.py") == "harness"
    assert classify.role(".github/workflows/ci.yml") == "harness"
    assert classify.role("src/app.py") == "source"
    assert classify.role("tests/__snapshots__/a.test.ts.snap") == "snapshot"
    assert classify.role(".proctor.toml") == "referee"
    assert classify.role("README.md") == "other"


def test_skip_in_comment_is_ignored():
    assert "P003" not in rules_of(mk("tests/test_a.py", ["# @pytest.mark.skip is banned here"]))


def test_xfail_and_xit_detected():
    assert "P003" in rules_of(mk("tests/test_a.py", ["@pytest.mark.xfail(strict=False)"]))
    assert "P003" in rules_of(mk("web/a.spec.js", ["xit('works', () => {})"]))


def test_test_aware_code_only_flags_source():
    assert "P010" in rules_of(mk("app/x.py", ["if 'pytest' in sys.modules: return"]))
    assert "P010" not in rules_of(mk("tests/test_x.py", ["if 'pytest' in sys.modules: return"]))
    assert "P010" in rules_of(mk("src/x.ts", ["if (process.env.NODE_ENV === 'test') return mock;"]))


def test_exit_in_cli_entrypoint_is_fine():
    assert "P009" not in rules_of(mk("pkg/cli.py", ["    sys.exit(0)"]))
    assert "P009" in rules_of(mk("tests/conftest.py", ["    sys.exit(0)"]))


def test_waiver_is_reported_not_hidden():
    res = scan_text(mk("tests/test_a.py", ["@pytest.mark.skip  # proctor: allow P003 -- upstream outage, JIRA-12"]))
    f = [x for x in res.findings if x.rule == "P003"][0]
    assert f.waived == "upstream outage, JIRA-12"
    assert res.verdict == "WARN"  # waived highs never pass silently


def test_disable_via_config():
    cfg = Config(disable={"P003"})
    assert "P003" not in {f.rule for f in scan_text(mk("tests/test_a.py", ["@pytest.mark.skip"]), config=cfg).findings}


def test_fail_on_medium():
    text = mk("svc/a.py", ["try:", "    x()", "except Exception:", "    pass"])
    assert scan_text(text).verdict == "WARN"
    assert scan_text(text, config=Config(fail_on="medium")).verdict == "FAIL"


def test_score_drops_with_findings():
    clean = scan_text(mk("app/a.py", ["def f():", "    return 2"]))
    dirty = scan_text(mk("tests/test_a.py", ["assert True"]))
    assert clean.score == 100 and dirty.score < 100


def test_literals_ignore_boring_and_keep_order():
    assert _literals('x = "utf-8"') == []
    assert _literals('f("hello world", 4242)') == ["'hello world'", "4242"]


def test_net_assertion_loss():
    text = mk("tests/test_a.py", ["    x = f()"], ["    assert f() == 1", "    assert g() == 2", "    assert h() == 3"])
    assert "P006" in rules_of(text)


def test_snapshot_regenerated_with_source_change():
    text = mk("src/render.py", ["    return '<b>' + s"], ["    return '<i>' + s"]) + \
        mk("tests/__snapshots__/render.snap", ["<b>hi</b>"], ["<i>hi</i>"])
    assert "P013" in rules_of(text)


def test_suppression_comment_is_low():
    res = scan_text(mk("src/a.ts", ["// @ts-ignore", "const x: number = 'a';"]))
    assert {f.severity for f in res.findings if f.rule == "P016"} == {"low"}
    assert res.verdict == "PASS"


def test_protected_paths_from_config():
    cfg = Config(protect=["evals/*"])
    res = scan_text(mk("evals/cases.jsonl", ['{"q": 1}']), config=cfg)
    assert any(f.rule == "P015" for f in res.findings) and res.verdict == "FAIL"


def test_claude_settings_only_flagged_when_proctor_hook_removed():
    path = ".claude/settings.json"
    assert "P015" not in rules_of(mk(path, ['  "permissions": {}'], ['  "model": "x"']))
    assert "P015" in rules_of(mk(path, [], ['        {"type": "command", "command": "proctor hook stop"}']))


def test_environment_gated_skip_is_low():
    res = scan_text(mk("tests/test_a.py", ["@pytest.mark.skipif(sys.version_info < (3, 12), reason='needs 3.12')"]))
    assert [f.severity for f in res.findings if f.rule == "P003"] == ["low"]
    multi = mk("tests/test_a.py", ["@pytest.mark.skipif(", "    sys.platform == 'win32', reason='posix only'", ")"])
    assert [f.severity for f in scan_text(multi).findings if f.rule == "P003"] == ["low"]
    assert scan_text(mk("tests/test_a.py", ["@pytest.mark.skipif(True, reason='later')"])).verdict == "FAIL"
