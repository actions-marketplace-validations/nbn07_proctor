from proctor.results import parse, with_files


def test_pytest_verbose_and_quiet():
    r = parse("===== 2 failed, 10 passed, 1 skipped in 0.42s =====")
    assert (r.framework, r.passed, r.failed, r.skipped) == ("pytest", 10, 2, 1)
    r = parse("3 failed, 3 passed in 0.02s")
    assert (r.passed, r.failed) == (3, 3)
    r = parse("1 passed, 2 errors in 0.1s")
    assert (r.passed, r.failed) == (1, 2)


def test_jest():
    r = parse("Tests:       1 failed, 1 skipped, 4 passed, 6 total\nTime: 1s")
    assert (r.framework, r.passed, r.failed, r.skipped) == ("jest", 4, 1, 1)


def test_vitest():
    r = parse(" Test Files  1 passed (1)\n      Tests  2 failed | 5 passed (7)\n")
    assert (r.framework, r.passed, r.failed) == ("vitest", 5, 2)


def test_go_verbose():
    out = "=== RUN   TestA\n--- PASS: TestA (0.00s)\n=== RUN   TestB\n--- FAIL: TestB (0.00s)\nFAIL\tpkg\t0.1s"
    r = parse(out)
    assert (r.framework, r.passed, r.failed) == ("go", 1, 1)


def test_cargo_sums_binaries():
    out = "test result: ok. 3 passed; 0 failed; 1 ignored;\ntest result: FAILED. 2 passed; 1 failed; 0 ignored;"
    r = parse(out)
    assert (r.passed, r.failed, r.skipped) == (5, 1, 1)


def test_unittest_and_mocha_and_tap():
    assert parse("Ran 5 tests in 0.01s\n\nFAILED (failures=1, errors=1)").passed == 3
    m = parse("  4 passing (20ms)\n  1 failing\n")
    assert (m.passed, m.failed) == (4, 1)
    t = parse("# tests 3\n# pass 2\n# fail 1\n")
    assert (t.framework, t.passed, t.failed) == ("tap", 2, 1)


def test_zero_tests_is_not_ok():
    r = parse("no tests ran in 0.01s", exit_code=0)
    assert not r.ok


def test_with_files():
    assert with_files("pytest -q", ["a.py", "b c.py"]) == "pytest -q a.py 'b c.py'"
    assert with_files("pytest {files} -x", ["a.py"]) == "pytest a.py -x"
    assert with_files("npm test", ["a.test.js"]) == "npm test -- a.test.js"
    assert with_files("go test ./...", ["x_test.go"]) == "go test ./..."
