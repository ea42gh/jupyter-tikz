from __future__ import annotations

from pathlib import Path

from jupyter_tikz.executor import render_svg_with_artifacts


class P:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_render_svg_with_artifacts_canonicalizes_page_suffix(monkeypatch, tmp_path: Path):
    """If the converter writes output-1.svg, we should still expose output.svg."""

    import subprocess

    def fake_run(cmd, cwd, stdout, stderr, text):
        workdir = Path(cwd)
        if cmd and cmd[0] == "latexmk":
            # Simulate latexmk producing the intermediate PDF.
            (workdir / "output.pdf").write_text("%PDF-1.4\n% dummy")
            return P(0)

        # Simulate the converter emitting a page-suffixed SVG.
        (workdir / "output-1.svg").write_text(
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\n"
            "<svg viewBox=\"0 0 10 10\"></svg>\n"
        )
        return P(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    tex = "\\documentclass{standalone}\\begin{document}x\\end{document}"

    artifacts = render_svg_with_artifacts(
        tex,
        output_dir=tmp_path,
        toolchain_name="pdftex_pdftocairo",
        crop="none",
    )

    assert artifacts.svg_path == tmp_path / "output.svg"
    assert (tmp_path / "output.svg").exists()
    assert (tmp_path / "output-1.svg").exists()
    assert artifacts.read_svg().lstrip().startswith("<svg")
