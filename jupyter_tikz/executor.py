from __future__ import annotations

import subprocess
import tempfile
import os
import shutil
from dataclasses import dataclass


from pathlib import Path
from typing import List

from jupyter_tikz.toolchains import Toolchain
from jupyter_tikz.toolchains import TOOLCHAINS
from jupyter_tikz.crop import (
    inkscape_tight_crop_svg_inplace,
    apply_viewbox_padding_inplace,
    normalize_padding,
)

#from typing import Sequence

# =======================================================================================================
def build_commands(
    toolchain: Toolchain,
    tex_file: Path,
    output_stem: str,
    *,
    crop: str | None = None,
) -> List[List[str]]:
    """
    Return the sequence of command invocations needed for this toolchain.
    Does not execute anything.
    """
    cmds: List[List[str]] = []

    # LaTeX step
    cmds.append(list(toolchain.latex_cmd) + [tex_file.name])

    # SVG conversion step
    if toolchain.needs_pdf:
        pdf = f"{output_stem}.pdf"
        svg = f"{output_stem}.svg"
        cmds.append(list(toolchain.svg_cmd) + [pdf, svg])
    elif toolchain.needs_dvi:
        dvi = f"{output_stem}.dvi"
        svg = f"{output_stem}.svg"
        cmds.append(_dvisvgm_svg_cmd(toolchain, crop) + [dvi, svg])

    return cmds


# -------------------------------------------------------------------------------------------------
# Option resolution (compact spec)
#
# Inputs
# ------
# - crop: None | "tight" | "page" | "none"
# - padding: None | number | str("2pt") | (x,y) | (l,r,t,b) | {left/right/top/bottom/x/y: ...}
#
# Resolution
# ----------
# 1) Resolve crop_mode:
#    - if crop is None: "tight" (back-compat)
#    - validate crop_mode in {"tight","page","none"}
# 2) Resolve padding_sides = normalize_padding(padding) -> (l,r,t,b) in SVG user units (96dpi)
# 3) Execute toolchain:
#    - if converter is dvisvgm and crop_mode != "none": add bbox args:
#         tight -> ["--bbox=min", "--exact-bbox"]
#         page  -> ["--bbox=papersize"]
#      otherwise: no bbox args
# 4) Post-process SVG:
#    - if crop_mode == "tight" and toolchain is PDF-based: attempt Inkscape tight crop (best-effort)
#    - always apply per-side padding by expanding viewBox (deterministic; no external deps)


def _resolve_crop_mode(crop: str | None) -> str:
    if crop is None:
        return "tight"
    crop_l = crop.lower().strip()
    if crop_l not in {"tight", "page", "none"}:
        raise ValueError(f"Invalid crop mode: {crop!r}")
    return crop_l


def _is_dvisvgm_toolchain(toolchain: Toolchain) -> bool:
    return bool(toolchain.needs_dvi) and len(toolchain.svg_cmd) > 0 and toolchain.svg_cmd[0] == "dvisvgm"


def _dvisvgm_svg_cmd(toolchain: Toolchain, crop: str | None) -> List[str]:
    """Return the svg_cmd for a dvisvgm toolchain with resolved bbox options."""
    base = list(toolchain.svg_cmd)
    if not _is_dvisvgm_toolchain(toolchain):
        return base

    mode = _resolve_crop_mode(crop)
    if mode == "none":
        return base
    if mode == "tight":
        # Tight bbox with more accurate glyph extents.
        return base + ["--bbox=min", "--exact-bbox"]
    # page
    return base + ["--bbox=papersize"]
# -------------------------------------------------------------------------------------------------------------------
def _run_toolchain_in_dir(
    toolchain: Toolchain,
    tex_source: str,
    workdir: Path,
    output_stem: str,
    *,
    crop: str | None = None,
    padding: object | None = None,
) -> RenderArtifacts:
    workdir.mkdir(parents=True, exist_ok=True)

    tex_path = workdir / f"{output_stem}.tex"
    tex_path.write_text(tex_source)

    crop_mode = _resolve_crop_mode(crop)
    # Validate/normalize padding early to fail fast.
    padding_sides = normalize_padding(padding)

    commands = build_commands(toolchain, tex_path, output_stem, crop=crop_mode)

    returncodes: List[int] = []
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    for cmd in commands:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
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

    pdf_path = workdir / f"{output_stem}.pdf"
    if not pdf_path.exists():
        pdf_path = None

    svg_path = workdir / f"{output_stem}.svg"
    if svg_path.exists():
        # Crop (best-effort; deterministic for dvisvgm via bbox flags)
        if crop_mode == "tight" and not _is_dvisvgm_toolchain(toolchain):
            inkscape_tight_crop_svg_inplace(svg_path)

        # Padding is always applied (deterministic; no external deps)
        if padding_sides != (0.0, 0.0, 0.0, 0.0):
            apply_viewbox_padding_inplace(svg_path, padding_sides)
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
# -------------------------------------------------------------------------------------------------------------------
def render_svg_with_artifacts(
    tex_source: str,
    *,
    output_dir: Path,
    toolchain_name: str = "pdftex_pdftocairo",
    output_stem: str = "output",
    crop: str | None = None,
    padding: object | None = None,
) -> RenderArtifacts:
    """
    Compile TeX and keep artifacts in output_dir.
    Returns paths to .tex/.pdf/.svg and captured stdout/stderr.
    """
    if toolchain_name not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {toolchain_name}")

    tc = TOOLCHAINS[toolchain_name]
    artifacts = _run_toolchain_in_dir(
        tc,
        tex_source,
        Path(output_dir),
        output_stem,
        crop=crop,
        padding=padding,
    )

    if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
        # include last stderr chunk to make failures actionable
        raise RenderError(
            "Toolchain execution failed. See stderr at: "
            f"{artifacts.stderr_path}"
        )

    if artifacts.svg_path is None:
        raise RenderError("SVG output not produced")

    return artifacts

class ExecutionResult:
    def __init__(self, returncodes, stdout, stderr, svg_text):
        self.returncodes = returncodes
        self.stdout = stdout
        self.stderr = stderr
        self.svg_text = svg_text
# -------------------------------------------------------------------------------------------------------------------
def run_toolchain(
    toolchain: Toolchain,
    tex_source: str,
    output_stem: str = "output",
    *,
    crop: str | None = None,
    padding: object | None = None,
) -> ExecutionResult:
    returncodes = []
    stdout = []
    stderr = []
    svg_text = None

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        tex_file = workdir / f"{output_stem}.tex"
        tex_file.write_text(tex_source)

        crop_mode = _resolve_crop_mode(crop)
        padding_sides = normalize_padding(padding)
        commands = build_commands(toolchain, tex_file, output_stem, crop=crop_mode)

        for cmd in commands:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),              # ← str() is correct
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            returncodes.append(proc.returncode)
            stdout.append(proc.stdout)
            stderr.append(proc.stderr)

            if proc.returncode != 0:
                break

        svg_path = workdir / f"{output_stem}.svg"
        if svg_path.exists():
            if crop_mode == "tight" and not _is_dvisvgm_toolchain(toolchain):
                inkscape_tight_crop_svg_inplace(svg_path)
            if padding_sides != (0.0, 0.0, 0.0, 0.0):
                apply_viewbox_padding_inplace(svg_path, padding_sides)
            svg_text = svg_path.read_text(errors="replace")

    # ← temp directory is cleaned up here, safely
    return ExecutionResult(
        returncodes=returncodes,
        stdout=stdout,
        stderr=stderr,
        svg_text=svg_text,
    )
# =======================================================================================================
class RenderError(RuntimeError):
    pass
# -------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RenderArtifacts:
    workdir: Path
    tex_path: Path
    pdf_path: Path | None
    svg_path: Path | None
    stdout_path: Path
    stderr_path: Path
    returncodes: List[int]

    def read_svg(self) -> str:
        if self.svg_path is None or not self.svg_path.exists():
            raise RenderError("SVG output not produced")
        return self.svg_path.read_text()
# -------------------------------------------------------------------------------------------------------------------
def render_svg(
    tex_source: str,
    *,
    toolchain_name: str = "pdftex_pdftocairo",
    output_stem: str = "output",
    crop: str | None = None,
    padding: object | None = None,
) -> str:
    """
    Compile TeX and return SVG text.

    Diagnostics
    -----------
    If compilation/conversion fails, the raised :class:`RenderError` will include a
    short tail of stderr and the LaTeX .log tail.

    For deeper debugging, set ``JUPYTER_TIKZ_KEEP_TEMP=1`` to keep the temporary
    build directory; the exception message will include the path.
    """
    if toolchain_name not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {toolchain_name}")

    tc = TOOLCHAINS[toolchain_name]
    keep = os.environ.get("JUPYTER_TIKZ_KEEP_TEMP") == "1"

    def _tail_file(path: Path, *, limit_chars: int = 8000) -> str:
        try:
            if not path.exists():
                return f"<missing: {path.name}>"
            txt = path.read_text(errors="replace")
        except Exception:
            return f"<unreadable: {path.name}>"
        if len(txt) <= limit_chars:
            return txt
        return txt[-limit_chars:]

    def _stderr_tail(stderr_path: Path, limit_chars: int = 4000) -> str:
        return _tail_file(stderr_path, limit_chars=limit_chars)

    def _latex_log_tail(workdir: Path, limit_chars: int = 8000) -> str:
        # pdflatex produces <jobname>.log, where jobname is output_stem
        return _tail_file(workdir / f"{output_stem}.log", limit_chars=limit_chars)

    if keep:
        workdir = Path(tempfile.mkdtemp(prefix="jupyter_tikz_"))
        try:
            artifacts = _run_toolchain_in_dir(
                tc,
                tex_source,
                workdir,
                output_stem,
                crop=crop,
                padding=padding,
            )
            if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
                stderr_tail = _stderr_tail(artifacts.stderr_path)
                log_tail = _latex_log_tail(workdir)
                raise RenderError(
                    "Toolchain execution failed. "
                    f"Artifacts kept at: {workdir}. "
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                    "---- stderr tail ----\n"
                    f"{stderr_tail}\n"
                    "---- latex log tail ----\n"
                    f"{log_tail}"
                )
            return artifacts.read_svg()
        except Exception:
            # Do not delete workdir when keep=1
            raise
    else:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            artifacts = _run_toolchain_in_dir(
                tc,
                tex_source,
                workdir,
                output_stem,
                crop=crop,
                padding=padding,
            )

            if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
                stderr_tail = _stderr_tail(artifacts.stderr_path)
                log_tail = _latex_log_tail(workdir)
                raise RenderError(
                    "Toolchain execution failed.\n"
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                    "---- stderr tail ----\n"
                    f"{stderr_tail}\n"
                    "---- latex log tail ----\n"
                    f"{log_tail}"
                )

            return artifacts.read_svg()
