"""Shared pytest fixtures for the jupyter_tikz test suite.

The upstream project commonly uses the third-party ``pytest-mock`` plugin.
To keep this repository's tests runnable in minimal environments, we provide
an internal ``mocker`` fixture that implements the subset of functionality
used by this suite (``spy`` and ``patch.object``).

We also:
  * register custom markers used throughout the suite, and
  * gate toolchain-dependent tests via ``needs_latex`` / ``needs_pdftocairo``.

The gating is *opt-out* (tests run when the relevant binaries are available).
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
from typing import Any, Optional

import pytest

from jupyter_tikz import TexDocument


# ---------------------------------------------------------------------------
# Stable sample inputs used by multiple tests
# ---------------------------------------------------------------------------

EXAMPLE_BAD_TIKZ = "HELLO WORLD"

EXAMPLE_GOOD_TEX = r"""
\documentclass[tikz]{standalone}
\begin{document}
    \begin{tikzpicture}
        \draw[fill=blue] (0, 0) rectangle (1, 1);
    \end{tikzpicture}
\end{document}"""

HASH_EXAMPLE_GOOD_TEX = md5(EXAMPLE_GOOD_TEX.strip().encode()).hexdigest()

TIKZ_CODE = r"""\begin{tikzpicture}
    \draw[fill=blue] (0, 0) rectangle (1, 1);
\end{tikzpicture}"""

EXAMPLE_TIKZ_BASIC_STANDALONE = r"\draw[fill=blue] (0, 0) rectangle (1, 1);"

RENDERED_SVG_PATH_GOOD_TIKZ = (
    "M -0.00195486 -0.00189963 L -0.00195486 28.345014 L 28.344959 28.345014 "
    "L 28.344959 -0.00189963 Z M -0.00195486 -0.00189963"
)

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
def tex_document() -> TexDocument:
    return TexDocument(ANY_CODE)


# ---------------------------------------------------------------------------
# Minimal internal replacement for the pytest-mock ``mocker`` fixture
# ---------------------------------------------------------------------------


@dataclass
class _PatchHandle:
    patcher: Any
    mock: Any


class SimpleMocker:
    """A tiny subset of pytest-mock's MockerFixture.

    Supports:
      * spy(obj, "attr")
      * patch.object(obj, "attr", ...)
    """

    def __init__(self) -> None:
        self._handles: list[_PatchHandle] = []

    def stopall(self) -> None:
        # Stop in reverse order (mirrors typical patch stacking semantics).
        for h in reversed(self._handles):
            try:
                h.patcher.stop()
            except Exception:
                # Best-effort cleanup; tests should surface any real issues.
                pass
        self._handles.clear()

    def spy(self, obj: Any, attribute: str):
        """Wrap an attribute and record calls while still executing it."""
        from unittest import mock

        original = getattr(obj, attribute)

        # Two cases:
        # 1) Spying on an *instance* method via an instance. Tests in this suite
        #    assert call signatures that do NOT include `self`. The most robust
        #    approach is to patch the *instance attribute* with a Mock that wraps
        #    the already-bound original method.
        # 2) Spying on a class attribute (e.g. TexDocument._render_jinja). Here
        #    binding must be preserved so the underlying method still receives
        #    `self` correctly. Tests do not assert arg lists in this case.
        if isinstance(obj, type):
            patcher = mock.patch.object(obj, attribute, autospec=True, wraps=original)
            m = patcher.start()
        else:
            wrapped = mock.Mock(wraps=original)
            patcher = mock.patch.object(obj, attribute, new=wrapped)
            m = patcher.start()

        self._handles.append(_PatchHandle(patcher=patcher, mock=m))
        return m

    class patch:  # noqa: N801 - keep API-compatible attribute name
        """Namespace mirroring pytest-mock's ``mocker.patch``."""

        @staticmethod
        def object(target: Any, attribute: str, *args: Any, **kwargs: Any):
            raise RuntimeError(
                "SimpleMocker.patch.object is a placeholder; use SimpleMocker.patch_object"
            )

    def patch_object(self, target: Any, attribute: str, *args: Any, **kwargs: Any):
        """Patch ``target.attribute`` and record the patch for teardown."""
        from unittest import mock

        patcher = mock.patch.object(target, attribute, *args, **kwargs)
        m = patcher.start()
        self._handles.append(_PatchHandle(patcher=patcher, mock=m))
        return m


@pytest.fixture
def mocker(request: pytest.FixtureRequest) -> SimpleMocker:
    """Compatibility fixture for suites written against pytest-mock."""
    m = SimpleMocker()

    # Provide ``mocker.patch.object`` as in pytest-mock.
    # We implement it via a bound method for teardown tracking.
    setattr(m.patch, "object", m.patch_object)

    request.addfinalizer(m.stopall)
    return m


# ---------------------------------------------------------------------------
# Marker registration + toolchain gating
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("jupyter_tikz")
    group.addoption(
        "--skip-render-tests",
        action="store_true",
        default=False,
        help="Skip tests marked needs_latex / needs_pdftocairo.",
    )
    group.addoption(
        "--latexmk",
        action="store",
        default=None,
        help="Path to latexmk executable (overrides PATH lookup).",
    )
    group.addoption(
        "--pdftocairo",
        action="store",
        default=None,
        help="Path to pdftocairo executable (overrides PATH lookup).",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "needs_latex: requires a LaTeX toolchain (latexmk + a TeX distribution)",
    )
    config.addinivalue_line(
        "markers",
        "needs_pdftocairo: requires pdftocairo in PATH (or --pdftocairo / env override)",
    )


def _which_with_override(
    *,
    cli_override: Optional[str],
    env_var: str,
    default_cmd: str,
) -> Optional[str]:
    import os
    import shutil

    cmd = cli_override or os.getenv(env_var) or default_cmd
    return shutil.which(cmd)


def pytest_runtest_setup(item: pytest.Item) -> None:
    import os

    if item.config.getoption("--skip-render-tests") or os.getenv(
        "JUPYTER_TIKZ_SKIP_RENDER_TESTS"
    ) in {"1", "true", "TRUE", "yes", "YES"}:
        if item.get_closest_marker("needs_latex") or item.get_closest_marker(
            "needs_pdftocairo"
        ):
            pytest.skip("render/toolchain tests skipped")

    if item.get_closest_marker("needs_latex"):
        latexmk = _which_with_override(
            cli_override=item.config.getoption("--latexmk"),
            env_var="JUPYTER_TIKZ_LATEXMKPATH",
            default_cmd="latexmk",
        )
        if latexmk is None:
            pytest.skip("latexmk not found")

    if item.get_closest_marker("needs_pdftocairo"):
        pdftocairo = _which_with_override(
            cli_override=item.config.getoption("--pdftocairo"),
            env_var="JUPYTER_TIKZ_PDFTOCAIROPATH",
            default_cmd="pdftocairo",
        )
        if pdftocairo is None:
            pytest.skip("pdftocairo not found")
