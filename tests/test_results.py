from proctor.results import can_target, parse, parse_report, run, with_files


def test_pytest_verbose_and_quiet():
    r = parse("===== 2 failed, 10 passed, 1 skipped in 0.42s =====")
    assert (r.framework, r.passed, r.failed, r.skipped) == ("pytest", 10, 2, 1)
    r = parse("3 failed, 3 passed in 0.02s")
    assert (r.passed, r.failed) == (3, 3)
    r = parse("586 passed, 10080 subtests passed in 28.55s")
    assert (r.passed, r.failed) == (586, 0)
    r = parse("2 failed, 584 passed, 3 subtests failed, 10077 subtests passed, 1 warning in 30.1s")
    assert (r.passed, r.failed) == (584, 2)
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


# ------------------------------------------------------------- compiled-language runners

def test_maven_aggregate_summed_across_modules():
    out = """
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.05 s - in com.acme.FooTest
[INFO] Results:
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0
[ERROR] Tests run: 2, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.1 s <<< FAILURE! - in com.acme.BarTest
[ERROR] Tests run: 5, Failures: 1, Errors: 1, Skipped: 1
"""
    r = parse(out, 1)
    assert (r.framework, r.passed, r.failed, r.skipped) == ("maven", 5, 2, 1)


def test_ctest():
    out = ("1/4 Test #1: a ....   Passed    0.01 sec\n\n75% tests passed, 1 tests failed out of 4\n\n"
           "The following tests did not run:\n\t  5 - Roman.DISABLED_X (Disabled)\n\n"
           "The following tests FAILED:\n\t  3 - Roman.Nine (Failed)\n")
    r = parse(out, 8)
    assert (r.framework, r.passed, r.failed, r.skipped) == ("ctest", 3, 1, 1)
    assert parse("No tests were found!!!\n").total == 0


def test_gtest_multiple_binaries():
    out = """[==========] 3 tests from 1 test suite ran. (0 ms total)
[  PASSED  ] 2 tests.
[  FAILED  ] 1 test, listed below:
[  FAILED  ] Roman.Nine

 1 FAILED TEST
  YOU HAVE 1 DISABLED TEST

[==========] 2 tests from 1 test suite ran. (0 ms total)
[  PASSED  ] 2 tests.
"""
    r = parse(out, 1)
    assert (r.framework, r.passed, r.failed, r.skipped) == ("gtest", 4, 1, 1)


def test_dotnet_and_catch2():
    out = "Failed!  - Failed:     1, Passed:    11, Skipped:     2, Total:    14, Duration: 1 s - A.Tests.dll\n" \
          "Passed!  - Failed:     0, Passed:     4, Skipped:     0, Total:     4, Duration: 1 s - B.Tests.dll\n"
    r = parse(out, 1)
    assert (r.framework, r.passed, r.failed, r.skipped) == ("dotnet", 15, 1, 2)
    old = "Total tests: 12\n     Passed: 11\n     Failed: 1\n"
    assert (parse(old).passed, parse(old).failed) == (11, 1)
    c = parse("test cases: 3 | 2 passed | 1 failed\nassertions: 9 | 8 passed | 1 failed\n")
    assert (c.framework, c.passed, c.failed) == ("catch2", 2, 1)
    assert parse("All tests passed (12 assertions in 4 test cases)").passed == 4


def test_junit_xml_and_trx(tmp_path):
    (tmp_path / "TEST-a.xml").write_text("""<?xml version="1.0"?>
<testsuite name="a" tests="4" failures="1" errors="0" skipped="1">
  <testcase classname="A" name="ok1"/>
  <testcase classname="A" name="ok2"/>
  <testcase classname="A" name="bad"><failure message="x"/></testcase>
  <testcase classname="A" name="skip"><skipped/></testcase>
</testsuite>""")
    assert parse_report(str(tmp_path / "TEST-a.xml")) == (2, 1, 1)
    (tmp_path / "gtest.xml").write_text("""<testsuites tests="2" failures="0" disabled="1" errors="0">
  <testsuite name="Roman" tests="2"><testcase name="A" status="run" result="completed"/>
  <testcase name="DISABLED_B" status="notrun" result="suppressed"/></testsuite></testsuites>""")
    assert parse_report(str(tmp_path / "gtest.xml")) == (1, 0, 1)
    (tmp_path / "r.trx").write_text("""<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">
  <ResultSummary outcome="Failed"><Counters total="5" executed="5" passed="3" failed="2" error="0"
   timeout="0" aborted="0" inconclusive="0" notExecuted="0"/></ResultSummary></TestRun>""")
    assert parse_report(str(tmp_path / "r.trx")) == (3, 2, 0)
    (tmp_path / "junk.xml").write_text("<not-xml")
    assert parse_report(str(tmp_path / "junk.xml")) is None


def test_stale_reports_are_ignored(tmp_path):
    import os
    import time
    stale = tmp_path / "target" / "surefire-reports" / "TEST-old.xml"
    stale.parent.mkdir(parents=True)
    stale.write_text('<testsuite tests="9"><testcase name="x"/></testsuite>')
    old = time.time() - 3600
    os.utime(stale, (old, old))
    # a run that writes no report must not inherit last hour's green result
    r = run("mvn() { echo 'BUILD FAILURE'; return 1; }; mvn test", str(tmp_path))
    assert r.reports == 0 and r.total == 0


def test_fresh_report_beats_console(tmp_path):
    cmd = ("mkdir -p out && printf '<testsuite><testcase name=\"a\"/><testcase name=\"b\"><failure/></testcase>"
           "</testsuite>' > out/r.xml && echo 'all good'")
    r = run(cmd, str(tmp_path), reports=["out/*.xml"])
    assert (r.framework, r.passed, r.failed, r.reports) == ("junit-xml", 1, 1, 1)


def test_with_files_for_jvm_dotnet_and_chains():
    files = ["src/test/java/com/acme/FooTest.java", "src/test/java/com/acme/BarIT.java"]
    assert with_files("mvn -B test", files) == "mvn -B test -Dtest=FooTest,BarIT -Dsurefire.failIfNoSpecifiedTests=false"
    assert with_files("./gradlew test", files) == "./gradlew test --tests '*FooTest' --tests '*BarIT'"
    assert "FullyQualifiedName~InvoiceTests" in with_files("dotnet test", ["tests/X.Tests/InvoiceTests.cs"])
    chain = "cmake --build build && ctest --test-dir build"
    assert with_files(chain, ["tests/a_test.cc"]) == chain and not can_target(chain)
    assert with_files("./bin/unit --gtest_filter='{names}.*'", ["tests/roman_test.cc"]) == "./bin/unit --gtest_filter='roman_test.*'"
