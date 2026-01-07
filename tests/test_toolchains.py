from __future__ import annotations

import pytest

from jupyter_tikz.executor import build_commands
from jupyter_tikz.toolchains import TOOLCHAINS


@pytest.mark.parametrize(
    "name, needs_pdf, needs_dvi",
    [
        ("pdftex_pdftocairo", True, False),
        ("pdftex_pdf2svg", True, False),
        ("pdftex_dvisvgm", False, True),
        ("xelatex_pdftocairo", True, False),
        ("xelatex_pdf2svg", True, False),
        ("xelatex_dvisvgm", False, True),
    ],
)
def test_registry_contains_expected_toolchains(name: str, needs_pdf: bool, needs_dvi: bool):
    tc = TOOLCHAINS[name]
    assert tc.name == name
    assert tc.needs_pdf is needs_pdf
    assert tc.needs_dvi is needs_dvi
    assert isinstance(tc.latex_cmd, (list, tuple)) and tc.latex_cmd
    assert isinstance(tc.svg_cmd, (list, tuple)) and tc.svg_cmd


@pytest.mark.parametrize(
    "name, expected_suffix",
    [
        ("pdftex_pdftocairo", ".pdf"),
        ("pdftex_pdf2svg", ".pdf"),
        ("pdftex_dvisvgm", ".dvi"),
        ("xelatex_pdftocairo", ".pdf"),
        ("xelatex_pdf2svg", ".pdf"),
        ("xelatex_dvisvgm", ".dvi"),
    ],
)
def test_build_commands_wires_expected_inputs(name: str, expected_suffix: str, tmp_path):
    # build_commands is a pure function; we validate wiring without invoking TeX.
    tc = TOOLCHAINS[name]
    tex_file = tmp_path / "job.tex"
    tex_file.write_text("\\documentclass{article}\\begin{document}x\\end{document}")

    cmds = build_commands(tc, tex_file, output_stem="job")
    assert len(cmds) == 2

    latex_cmd, svg_cmd = cmds
    # LaTeX command should target the .tex input by filename (run in workdir).
    assert latex_cmd[-1] == tex_file.name
    # Conversion step should take either job.pdf or job.dvi.
    # For dvisvgm, we pass the output file via --output=... and keep only the
    # DVI as a positional argument.
    if svg_cmd[0] == "dvisvgm":
        assert svg_cmd[-1].endswith(expected_suffix)
        assert any(arg.startswith("--output=") and arg.endswith("job.svg") for arg in svg_cmd)
        assert any(arg.startswith("--page=") for arg in svg_cmd)
    else:
        assert svg_cmd[-2].endswith(expected_suffix)
        assert svg_cmd[-1].endswith(".svg")
