from __future__ import annotations

from hashlib import md5
from pathlib import Path

import jupyter_tikz.executor as ex
from jupyter_tikz.executor import RenderArtifacts


def _fake_run_toolchain_in_dir(
    toolchain,
    tex_source: str,
    workdir: Path,
    output_stem: str,
    **kwargs,
) -> RenderArtifacts:
    """Simulate a successful toolchain run without invoking external binaries."""
    workdir.mkdir(parents=True, exist_ok=True)

    tex_path = workdir / f"{output_stem}.tex"
    svg_path = workdir / f"{output_stem}.svg"
    stdout_path = workdir / f"{output_stem}.stdout.txt"
    stderr_path = workdir / f"{output_stem}.stderr.txt"

    tex_path.write_text(tex_source)
    svg_path.write_text("<svg><g/></svg>")
    stdout_path.write_text("ok")
    stderr_path.write_text("")

    return RenderArtifacts(
        workdir=workdir,
        tex_path=tex_path,
        pdf_path=None,
        svg_path=svg_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncodes=[0, 0],
    )


def test_artifacts_path_prefix_writes_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_run_toolchain_in_dir", _fake_run_toolchain_in_dir)

    artifacts_prefix = tmp_path / "kept" / "my_render"
    tex = r"\documentclass{article}\begin{document}x\end{document}"

    svg_text = ex.render_svg(
        tex,
        toolchain_name="pdftex_pdftocairo",
        artifacts_path=artifacts_prefix,
    )

    assert "<svg" in svg_text
    assert (tmp_path / "kept" / "my_render.tex").exists()
    assert (tmp_path / "kept" / "my_render.svg").exists()
    assert (tmp_path / "kept" / "my_render.stdout.txt").exists()
    assert (tmp_path / "kept" / "my_render.stderr.txt").exists()


def test_artifacts_path_directory_uses_unique_stem(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_run_toolchain_in_dir", _fake_run_toolchain_in_dir)

    artifacts_dir = tmp_path / "kept_dir"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    tex = "any tex"
    svg_text = ex.render_svg(
        tex,
        toolchain_name="pdftex_pdftocairo",
        output_stem="job",
        artifacts_path=artifacts_dir,
    )
    assert "<svg" in svg_text

    h8 = md5(tex.encode("utf-8")).hexdigest()[:8]
    stem = f"job-{h8}"

    assert (artifacts_dir / f"{stem}.tex").exists()
    assert (artifacts_dir / f"{stem}.svg").exists()
