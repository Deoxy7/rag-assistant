"""The venv must contain exactly what requirements.txt pins — no more, no less.

If someone `pip install`s a package to try it and forgets to pin it, results
would depend on a package a fresh clone doesn't have. This test catches that.
"""

import re
from importlib.metadata import distributions
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"
IGNORED = {"pip", "setuptools", "wheel"}  # the venv's own tooling, pinned by the Makefile


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned() -> dict[str, str]:
    pins = {}
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, version = line.partition("==")
        assert sep, f"requirements.txt line is not pinned with ==: {line!r}"
        pins[canonical(name)] = version.strip()
    return pins


def installed() -> dict[str, str]:
    return {canonical(d.metadata["Name"]): d.version for d in distributions()
            if canonical(d.metadata["Name"]) not in IGNORED}


def test_every_requirement_is_pinned_with_double_equals():
    assert pinned()


def test_venv_matches_requirements_exactly():
    want, have = pinned(), installed()
    missing = {n: v for n, v in want.items() if have.get(n) != v}
    extra = {n: v for n, v in have.items() if n not in want}
    assert not missing, f"pinned but not installed at that version: {missing}"
    assert not extra, f"installed but not pinned in requirements.txt: {extra}"
