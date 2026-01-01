import shutil
import pytest

from jupyter_tikz.executor import render_svg


@pytest.mark.needs_latex
def test_render_svg_basic():
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

    svg = render_svg(tex)

    assert "<svg" in svg
    assert "</svg>" in svg

