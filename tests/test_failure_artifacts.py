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
