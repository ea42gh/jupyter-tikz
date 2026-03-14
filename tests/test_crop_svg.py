import os
import shutil

import pytest

from jupyter_tikz.executor import render_svg


@pytest.mark.needs_latex
def test_render_svg_with_cropping():
    if shutil.which("latexmk") is None:
        pytest.skip("latexmk not installed")
    pdftocairo = os.environ.get("JUPYTER_TIKZ_PDFTOCAIROPATH") or "pdftocairo"
    if shutil.which(pdftocairo) is None:
        pytest.skip(f"pdftocairo not found: {pdftocairo!r}")
    if shutil.which("inkscape") is None:
        pytest.skip("inkscape not installed")

    tex = r"""
    \documentclass{standalone}
    \begin{document}
    \rule{10cm}{1cm}
    \end{document}
    """

    svg = render_svg(tex)

    assert "<svg" in svg
    assert "width" in svg or "viewBox" in svg
