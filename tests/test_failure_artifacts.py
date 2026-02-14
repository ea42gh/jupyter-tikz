import re
import shutil
from pathlib import Path

import pytest


def test_render_svg_keeps_artifacts_on_failure(monkeypatch):
    import jupyter_tikz.executor as ex

    def fake_run_toolchain_in_dir(toolchain, tex_source, workdir, output_stem, **kwargs):
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / f"{output_stem}.tex").write_text(tex_source)
        (workdir / f"{output_stem}.stderr.txt").write_text("boom\n")
        (workdir / f"{output_stem}.stdout.txt").write_text("")
        (workdir / f"{output_stem}.log").write_text("latex log\n")

        return ex.RenderArtifacts(
            workdir=workdir,
            tex_path=workdir / f"{output_stem}.tex",
            pdf_path=None,
            svg_path=None,
            stdout_path=workdir / f"{output_stem}.stdout.txt",
            stderr_path=workdir / f"{output_stem}.stderr.txt",
            returncodes=[1],
        )

    monkeypatch.setattr(ex, "_run_toolchain_in_dir", fake_run_toolchain_in_dir)

    with pytest.raises(ex.RenderError) as ei:
        ex.render_svg(
            "\\documentclass{article}\\begin{document}x\\end{document}",
            toolchain_name="pdftex_pdftocairo",
            cache=False,
        )

    msg = str(ei.value)
    m = re.search(r"Artifacts kept at: ([^\n]+?)(?:\.\n|\.)", msg)
    assert m, msg
    kept = Path(m.group(1))
    assert kept.exists()
    assert (kept / "output.stderr.txt").exists()
    assert (kept / "output.log").exists()

    # Cleanup to avoid polluting /tmp across test runs.
    shutil.rmtree(kept, ignore_errors=True)


def test_render_svg_with_artifacts_includes_diagnostics_tail(monkeypatch, tmp_path):
    import jupyter_tikz.executor as ex

    def fake_run_toolchain_in_dir(toolchain, tex_source, workdir, output_stem, **kwargs):
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / f"{output_stem}.tex").write_text(tex_source)
        (workdir / f"{output_stem}.stderr.txt").write_text("boom\n")
        (workdir / f"{output_stem}.stdout.txt").write_text("")
        (workdir / f"{output_stem}.log").write_text("latex log\n")
        return ex.RenderArtifacts(
            workdir=workdir,
            tex_path=workdir / f"{output_stem}.tex",
            pdf_path=None,
            svg_path=None,
            stdout_path=workdir / f"{output_stem}.stdout.txt",
            stderr_path=workdir / f"{output_stem}.stderr.txt",
            returncodes=[1],
        )

    monkeypatch.setattr(ex, "_run_toolchain_in_dir", fake_run_toolchain_in_dir)

    with pytest.raises(ex.RenderError) as ei:
        ex.render_svg_with_artifacts(
            "\\documentclass{article}\\begin{document}x\\end{document}",
            toolchain_name="pdftex_pdftocairo",
            output_dir=tmp_path,
            output_stem="output",
        )

    msg = str(ei.value)
    assert "Artifacts kept at:" in msg
    assert "See stderr at:" in msg
    assert "---- stderr tail ----" in msg
    assert "boom" in msg
    assert "---- latex log tail ----" in msg
    assert "latex log" in msg


def test_render_base_svg_uncached_includes_full_diagnostics(monkeypatch, tmp_path):
    import jupyter_tikz.executor as ex

    def fake_run_toolchain_in_dir(toolchain, tex_source, workdir, output_stem, **kwargs):
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / f"{output_stem}.tex").write_text(tex_source)
        (workdir / f"{output_stem}.stderr.txt").write_text("boom\n")
        (workdir / f"{output_stem}.stdout.txt").write_text("")
        (workdir / f"{output_stem}.log").write_text("latex log\n")
        return ex.RenderArtifacts(
            workdir=workdir,
            tex_path=workdir / f"{output_stem}.tex",
            pdf_path=None,
            svg_path=None,
            stdout_path=workdir / f"{output_stem}.stdout.txt",
            stderr_path=workdir / f"{output_stem}.stderr.txt",
            returncodes=[1],
        )

    monkeypatch.setattr(ex, "_run_toolchain_in_dir", fake_run_toolchain_in_dir)

    with pytest.raises(ex.RenderError) as ei:
        ex._render_base_svg_uncached(
            "\\documentclass{article}\\begin{document}x\\end{document}",
            "pdftex_pdftocairo",
            output_stem="output",
            crop_mode="tight",
            enforce_tight_crop=True,
            exact_bbox=False,
        )

    msg = str(ei.value)
    assert "Toolchain execution failed." in msg
    assert "---- stderr tail ----" in msg
    assert "boom" in msg
    assert "---- latex log tail ----" in msg
    assert "latex log" in msg
