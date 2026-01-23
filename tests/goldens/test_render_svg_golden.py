import shutil
import pytest
from pathlib import Path

from jupyter_tikz import render_svg
from jupyter_tikz.executor import resolve_toolchain_name
from jupyter_tikz.svg_normalize import normalize_svg

# << DBG
#from jupyter_tikz.executor import resolve_toolchain_name, resolve_crop_policy
#from jupyter_tikz.toolchains import TOOLCHAINS
# DBG >>

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

    # << DBG
    #tc_name = resolve_toolchain_name(None)
    #tc = TOOLCHAINS[tc_name]
    #mode, enforce = resolve_crop_policy(None, tc)

    #print("toolchain:", tc_name)
    #print("crop policy:", mode, enforce)
    #print("has inkscape metadata in output:", "xmlns:inkscape" in svg)
    #print("svg head:", svg[:200])
    #print("expected head:", expected[:200])
    # DBG >>

    assert svg == expected
