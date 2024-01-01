from __future__ import annotations

import py_compile
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"

FORBIDDEN_PATTERNS = [
    re.compile(r"sk_live", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{8,}"),
    re.compile(r"ASIA[0-9A-Z]{8,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r'"private_key"\s*:'),
]


def test_examples_compile() -> None:
    for path in sorted(EXAMPLES_DIR.glob("*.py")):
        py_compile.compile(str(path), doraise=True)


def test_examples_do_not_contain_realistic_secret_literals() -> None:
    for path in sorted(EXAMPLES_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            assert not pattern.search(text), f"{path.name} matches {pattern.pattern}"
