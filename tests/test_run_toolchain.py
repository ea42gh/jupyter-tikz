import shutil
import pytest

from jupyter_tikz.toolchains import TOOLCHAINS
from jupyter_tikz.executor import run_toolchain


@pytest.mark.needs_latex
def test_run_toolchain_basic_pdftocairo():
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

    tc = TOOLCHAINS["pdftex_pdftocairo"]

    result = run_toolchain(tc, tex, output_stem="hello")

    assert result.returncodes
    assert result.returncodes[0] == 0

