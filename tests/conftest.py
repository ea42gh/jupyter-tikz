from __future__ import annotations

import os
import shutil
import sys
from hashlib import md5
from pathlib import Path

import pytest

# Ensure the local checkout wins over any site-packages install.
# This prevents confusing import errors when a developer has an older
# jupyter_tikz installed globally.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if (_PROJECT_ROOT / "jupyter_tikz").is_dir() and str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from jupyter_tikz import TexDocument

EXAMPLE_BAD_TIKZ = "HELLO WORLD"

EXAMPLE_GOOD_TEX = r"""
\documentclass[tikz]{standalone}
\begin{document}
    \begin{tikzpicture}
        \draw[fill=blue] (0, 0) rectangle (1, 1);
    \end{tikzpicture}
\end{document}"""

HASH_EXAMPLE_GOOD_TEX = md5(EXAMPLE_GOOD_TEX.strip().encode()).hexdigest()

# LATEX_CODE = r"""\documentclass{standalone}
# \usepackage{tikz}
# \begin{document}
# \begin{tikzpicture}
#     \draw[fill=blue] (0, 0) rectangle (1, 1);
# \end{tikzpicture}
# \end{document}"""

TIKZ_CODE = r"""\begin{tikzpicture}
    \draw[fill=blue] (0, 0) rectangle (1, 1);
\end{tikzpicture}"""

EXAMPLE_TIKZ_BASIC_STANDALONE = r"\draw[fill=blue] (0, 0) rectangle (1, 1);"

RENDERED_SVG_PATH_GOOD_TIKZ = "M -0.00195486 -0.00189963 L -0.00195486 28.345014 L 28.344959 28.345014 L 28.344959 -0.00189963 Z M -0.00195486 -0.00189963"

EXAMPLE_VIEWBOX_CODE_INPUT = r"""
\draw (-2.5,-2.5) rectangle (5,5);
"""
EXAMPLE_PARENT_WITH_INPUT_COMMANDT = r"""
\documentclass[tikz]{standalone}
\begin{document}
    \begin{tikzpicture}
        \input{viewbox.tex}
        \node[draw] at (0,0) {Hello, World!};
    \end{tikzpicture}
\end{document}    
"""

EXAMPLE_JINJA_TEMPLATE = r"""
\documentclass[tikz]{standalone}
\begin{document}
    \begin{tikzpicture}
        (~ A Jinja Template Commentary ~)
        (** for person in people **)
        \node[draw] at (0,(* person.y *)) {Hello, (* person.name *)!};
        (** endfor **)
    \end{tikzpicture}
\end{document}"""

DUMMY_COMMAND = "dummy_command"

ANY_CODE_HASH = md5("any code".encode()).hexdigest()
ANY_CODE = "any code"


@pytest.fixture
def tex_document():
    return TexDocument(ANY_CODE)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--skip-render-tests",
        action="store_true",
        default=False,
        help="Skip tests that require the external TeX/toolchain.",
    )
    parser.addoption(
        "--pdftocairo",
        action="store",
        default=None,
        help="Path to pdftocairo executable (overrides PATH and env var).",
    )
    parser.addoption(
        "--latexmk",
        action="store",
        default=None,
        help="Path to latexmk executable (overrides PATH).",
    )


def _resolve_executable(config: pytest.Config, *, option_name: str, env_name: str | None, default: str) -> str | None:
    override = config.getoption(option_name)
    if override:
        return override if shutil.which(override) else None
    if env_name:
        env_val = os.environ.get(env_name)
        if env_val:
            return env_val if shutil.which(env_val) else None
    return shutil.which(default)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Run render/toolchain tests by default.

    Tests are skipped only when the required external executables are genuinely
    missing, or when the user opts out via --skip-render-tests or
    JUPYTER_TIKZ_SKIP_RENDER_TESTS=1.
    """

    opt_out = bool(config.getoption("--skip-render-tests")) or os.environ.get("JUPYTER_TIKZ_SKIP_RENDER_TESTS") == "1"

    latexmk_path = _resolve_executable(config, option_name="--latexmk", env_name=None, default="latexmk")
    pdftocairo_path = _resolve_executable(
        config,
        option_name="--pdftocairo",
        env_name="JUPYTER_TIKZ_PDFTOCAIROPATH",
        default="pdftocairo",
    )

    skip_render = pytest.mark.skip(reason="render/toolchain tests skipped (--skip-render-tests or JUPYTER_TIKZ_SKIP_RENDER_TESTS=1)")
    skip_latex = pytest.mark.skip(reason="latexmk not found")
    skip_pdftocairo = pytest.mark.skip(reason="pdftocairo not found")

    for item in items:
        needs_latex = item.get_closest_marker("needs_latex") is not None
        needs_pdftocairo = item.get_closest_marker("needs_pdftocairo") is not None

        if opt_out and (needs_latex or needs_pdftocairo):
            item.add_marker(skip_render)
            continue

        if needs_latex and latexmk_path is None:
            item.add_marker(skip_latex)
            continue

        if needs_pdftocairo and pdftocairo_path is None:
            item.add_marker(skip_pdftocairo)


def pytest_configure(config: pytest.Config) -> None:
    # Register custom markers to avoid "unknown marker" warnings.
    config.addinivalue_line("markers", "needs_latex: requires latexmk (and a TeX toolchain)")
    config.addinivalue_line("markers", "needs_pdftocairo: requires pdftocairo")
