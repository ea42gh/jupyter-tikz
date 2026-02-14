import re
from pathlib import Path

import jupyter_tikz


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    txt = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', txt, flags=re.MULTILINE)
    assert m is not None
    assert jupyter_tikz.__version__ == m.group(1)
