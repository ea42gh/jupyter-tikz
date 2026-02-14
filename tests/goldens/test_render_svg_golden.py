import shutil
import pytest
from pathlib import Path

from jupyter_tikz import render_svg
from jupyter_tikz.executor import resolve_toolchain_name
from jupyter_tikz.svg_normalize import normalize_svg

@pytest.mark.needs_latex
def test_render_svg_basic_golden():
    if shutil.which("latexmk") is None:
        pytest.skip("latexmk not installed")
    if shutil.which("pdftocairo") is None:
        pytest.skip("pdftocairo not installed")

    tex = r"""
    \documentclass{standalone}
    \begin{document}
    Hello
    \end{document}
    """

    toolchain = resolve_toolchain_name(None)
    svg = normalize_svg(render_svg(tex, toolchain_name=toolchain))

    golden = Path(__file__).parent / "basic_text.svg"
    expected = normalize_svg(golden.read_text())

    assert svg == expected
