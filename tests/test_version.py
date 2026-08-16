import re
from pathlib import Path

import jupyter_tikz


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    txt = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', txt, flags=re.MULTILINE)
    assert m is not None
    assert jupyter_tikz.__version__ == m.group(1)


def _first_changelog_version(text: str) -> str | None:
    m = re.search(r"^##\s+v([0-9]+\.[0-9]+\.[0-9]+)\s*$", text, flags=re.MULTILINE)
    return m.group(1) if m else None


def test_version_strings_are_consistent_across_package_and_docs():
    root = Path(__file__).resolve().parents[1]

    pyproject_txt = (root / "pyproject.toml").read_text(encoding="utf-8")
    py_m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_txt, flags=re.MULTILINE)
    assert py_m is not None
    py_ver = py_m.group(1)

    docs_changelog_txt = (root / "docs" / "about" / "changelog.md").read_text(
        encoding="utf-8"
    )
    docs_ver = _first_changelog_version(docs_changelog_txt)
    assert docs_ver is not None

    readme_txt = (root / "README.md").read_text(encoding="utf-8")
    readme_changelog = readme_txt.split("# Changelog", 1)[1]
    readme_ver = _first_changelog_version(readme_changelog)
    assert readme_ver is not None

    assert jupyter_tikz.__version__ == py_ver == docs_ver == readme_ver
