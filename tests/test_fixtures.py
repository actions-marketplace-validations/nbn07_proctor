"""The rogues' gallery: every known cheat must be caught, every honest change must pass."""

import glob
import os
import re

import pytest

from proctor.engine import scan_text

HERE = os.path.dirname(__file__)
CHEATS = sorted(glob.glob(os.path.join(HERE, "fixtures", "cheats", "*.diff")))
HONEST = sorted(glob.glob(os.path.join(HERE, "fixtures", "honest", "*.diff")))


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("path", CHEATS, ids=[os.path.basename(p) for p in CHEATS])
def test_cheat_is_caught(path):
    text = _read(path)
    expected = {e.strip() for e in re.search(r"# expect: (.+)", text).group(1).split(",")}
    res = scan_text(text)
    got = {f.rule for f in res.findings}
    assert expected <= got, f"missed {expected - got}; got {got}"
    assert res.verdict in ("FAIL", "WARN")


@pytest.mark.parametrize("path", HONEST, ids=[os.path.basename(p) for p in HONEST])
def test_honest_change_passes(path):
    res = scan_text(_read(path))
    noisy = [f"{f.rule} {f.path}:{f.line} {f.message}" for f in res.findings if f.severity != "low"]
    assert not noisy
    assert res.verdict == "PASS"


def test_gallery_is_big_enough():
    assert len(CHEATS) >= 20 and len(HONEST) >= 8
