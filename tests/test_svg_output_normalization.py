from __future__ import annotations

from pathlib import Path

import pytest

from jupyter_tikz.executor import RenderArtifacts, run_toolchain, strip_svg_xml_declaration
from jupyter_tikz.toolchains import TOOLCHAINS


def test_strip_svg_xml_declaration_removes_prolog_and_doctype():
    raw = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\n"
        "<!DOCTYPE svg PUBLIC \"-//W3C//DTD SVG 1.1//EN\" "
        "\"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd\">\n"
        "<svg viewBox=\"0 0 10 10\"></svg>\n"
    )
    out = strip_svg_xml_declaration(raw)
    assert out.lstrip().startswith("<svg")
    assert "<?xml" not in out
    assert "<!DOCTYPE" not in out


def test_render_artifacts_read_svg_strips_by_default(tmp_path: Path):
    svg_path = tmp_path / "output.svg"
    svg_path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\n"
        "<svg viewBox=\"0 0 10 10\"></svg>\n"
    )
    tex_path = tmp_path / "output.tex"
    tex_path.write_text("% dummy")
    stdout_path = tmp_path / "output.stdout.txt"
    stderr_path = tmp_path / "output.stderr.txt"
    stdout_path.write_text("")
    stderr_path.write_text("")

    artifacts = RenderArtifacts(
        workdir=tmp_path,
        tex_path=tex_path,
        pdf_path=None,
        svg_path=svg_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncodes=[0],
    )

    assert artifacts.read_svg().lstrip().startswith("<svg")
    assert artifacts.read_svg(strip_xml_declaration=False).lstrip().startswith("<?xml")


def test_run_toolchain_strip_xml_declaration_toggle(monkeypatch):
    """run_toolchain should normalize inline SVG text for notebook consumers."""

    tc = TOOLCHAINS["pdftex_pdftocairo"]

    class P:
        def __init__(self, returncode: int = 0):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = ""

    def fake_run(cmd, cwd, stdout, stderr, text):
        workdir = Path(cwd)
        # Simulate latexmk producing the intermediate PDF.
        if cmd and cmd[0] == "latexmk":
            (workdir / "output.pdf").write_text("%PDF-1.4\n% dummy")
            return P(0)
        # Simulate the converter emitting an SVG with an XML prolog.
        out_svg = workdir / "output.svg"
        out_svg.write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\n"
            "<svg viewBox=\"0 0 10 10\"></svg>\n"
        )
        return P(0)

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)

    tex = "\\documentclass{standalone}\\begin{document}x\\end{document}"

    res = run_toolchain(tc, tex, crop="none", strip_xml_declaration=True)
    assert res.svg_text is not None
    assert res.svg_text.lstrip().startswith("<svg")

    res2 = run_toolchain(tc, tex, crop="none", strip_xml_declaration=False)
    assert res2.svg_text is not None
    assert res2.svg_text.lstrip().startswith("<?xml")
