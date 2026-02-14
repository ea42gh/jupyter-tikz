import os
import shutil
from dataclasses import is_dataclass

import pytest

from jupyter_tikz.executor import ExecutionResult, run_toolchain
from jupyter_tikz.toolchains import TOOLCHAINS


@pytest.mark.needs_latex
def test_run_toolchain_basic_pdftocairo():
    if shutil.which("latexmk") is None:
        pytest.skip("latexmk not installed")
    pdftocairo = os.environ.get("JUPYTER_TIKZ_PDFTOCAIROPATH") or "pdftocairo"
    if shutil.which(pdftocairo) is None:
        pytest.skip(f"pdftocairo not found: {pdftocairo!r}")

    tex = r"""
    \documentclass{standalone}
    \begin{document}
    Hello
    \end{document}
    """

    tc = TOOLCHAINS["pdftex_pdftocairo"]

    result = run_toolchain(tc, tex, output_stem="hello")

    assert is_dataclass(ExecutionResult)
    assert isinstance(result, ExecutionResult)
    assert result.returncodes
    assert result.returncodes[0] == 0
    assert isinstance(result.stdout_text, str)
    assert isinstance(result.stderr_text, str)
