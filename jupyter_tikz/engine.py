from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from jupyter_tikz.artifacts import (
    canonicalize_svg_output_path,
    find_svg_output_path,
)
from jupyter_tikz.commands import build_commands
from jupyter_tikz.crop import crop_svg_inplace
from jupyter_tikz.process import build_subprocess_env, run_latex_passes
from jupyter_tikz.render_types import RenderArtifacts
from jupyter_tikz.svg_box import Padding, apply_padding_to_svg_file
from jupyter_tikz.toolchains import Toolchain


def run_toolchain_in_dir(
    toolchain: Toolchain,
    tex_source: str,
    workdir: Path,
    output_stem: str,
    *,
    crop_mode: Literal["tight", "page", "none"],
    enforce_tight_crop: bool,
    exact_bbox: bool,
    padding: Padding,
) -> RenderArtifacts:
    workdir.mkdir(parents=True, exist_ok=True)

    tex_source = tex_source.replace("ᵀ", "^{T}")

    tex_path = workdir / f"{output_stem}.tex"
    tex_path.write_text(tex_source, encoding="utf-8", newline="\n")

    commands = build_commands(
        toolchain,
        tex_path,
        output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
    )

    run_env = build_subprocess_env()
    returncodes, stdout_chunks, stderr_chunks = run_latex_passes(
        toolchain,
        tex_path,
        workdir=workdir,
        env=run_env,
    )

    if not returncodes or returncodes[-1] == 0:
        for cmd in commands[1:]:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                env=run_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            returncodes.append(proc.returncode)
            stdout_chunks.append(proc.stdout)
            stderr_chunks.append(proc.stderr)

            if proc.returncode != 0:
                break

    stdout_path = workdir / f"{output_stem}.stdout.txt"
    stderr_path = workdir / f"{output_stem}.stderr.txt"
    stdout_path.write_text("".join(stdout_chunks))
    stderr_path.write_text("".join(stderr_chunks))

    pdf_candidate = workdir / f"{output_stem}.pdf"
    pdf_path: Path | None = pdf_candidate if pdf_candidate.exists() else None

    svg_path = canonicalize_svg_output_path(
        workdir,
        output_stem,
        find_svg_output_path(workdir, output_stem),
    )
    if svg_path is not None and svg_path.exists():
        if enforce_tight_crop and crop_mode == "tight":
            crop_svg_inplace(svg_path)

        # Padding is deterministic and toolchain-agnostic.
        if not padding.is_zero():
            apply_padding_to_svg_file(svg_path, padding)
    else:
        svg_path = None

    return RenderArtifacts(
        workdir=workdir,
        tex_path=tex_path,
        pdf_path=pdf_path,
        svg_path=svg_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncodes=returncodes,
    )


_run_toolchain_in_dir = run_toolchain_in_dir
