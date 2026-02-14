from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import pytest

import jupyter_tikz.executor as executor


def _fake_subprocess_run_factory(output_stem: str):
    """Return a subprocess.run replacement that writes expected artifacts.

    This lets us unit-test post-processing call order without requiring external
    TeX/conversion binaries.
    """

    def _svg_output_arg(cmd: Sequence[str]) -> Optional[str]:
        for arg in cmd:
            if isinstance(arg, str) and arg.startswith("--output=") and arg.endswith(".svg"):
                return arg.split("=", 1)[1]
        for arg in cmd:
            if isinstance(arg, str) and arg.endswith(".svg") and "=" not in arg:
                return arg
        return None

    def fake_run(cmd, cwd=None, env=None, stdout=None, stderr=None, text=None, timeout=None):
        workdir = Path(cwd) if cwd else Path(".")
        # Always create placeholder build outputs that downstream code expects.
        (workdir / f"{output_stem}.log").write_text("log")
        (workdir / f"{output_stem}.pdf").write_bytes(b"%PDF-1.4\n%")
        (workdir / f"{output_stem}.dvi").write_bytes(b"DVI")

        svg_rel = _svg_output_arg(cmd)
        if svg_rel:
            svg_path = workdir / svg_rel
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            svg_path.write_text('<svg viewBox="0 0 10 10" width="10" height="10"></svg>')

        class P:
            returncode = 0
            stdout = ""
            stderr = ""

        return P()

    return fake_run


@pytest.mark.parametrize(
    "toolchain_name,crop,expect_calls",
    [
        ("pdftex_pdftocairo", "tight", ["crop", "padding", "frame"]),
        ("pdftex_pdftocairo", "page", ["padding", "frame"]),
        ("pdftex_dvisvgm", "tight", ["padding", "frame"]),
    ],
)
def test_render_svg_with_artifacts_postprocess_order(
    monkeypatch, tmp_path, toolchain_name: str, crop: str, expect_calls: list[str]
):
    calls: list[str] = []

    def _rec(name: str):
        def _fn(*args, **kwargs):
            calls.append(name)
            return True

        return _fn

    monkeypatch.setattr(executor, "crop_svg_inplace", _rec("crop"))
    monkeypatch.setattr(executor, "apply_padding_to_svg_file", _rec("padding"))
    monkeypatch.setattr(executor, "apply_canvas_frame_to_svg_file", _rec("frame"))

    monkeypatch.setattr(executor.subprocess, "run", _fake_subprocess_run_factory("job"))

    tex = r"\\documentclass{standalone}\\begin{document}x\\end{document}"
    artifacts = executor.render_svg_with_artifacts(
        tex,
        output_dir=tmp_path,
        toolchain_name=toolchain_name,
        output_stem="job",
        crop=crop,
        padding=(1, 2, 3, 4),
        frame=True,
    )

    assert artifacts.svg_path is not None
    assert artifacts.svg_path.exists()
    assert calls == expect_calls
