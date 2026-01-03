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
from jupyter_tikz.crop import crop_svg_inplace

#from typing import Sequence

# =======================================================================================================
def build_commands(
    toolchain: Toolchain,
    tex_file: Path,
    output_stem: str,
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
        cmds.append(list(toolchain.svg_cmd) + [dvi, svg])

    return cmds
# -------------------------------------------------------------------------------------------------------------------
def _run_toolchain_in_dir(
    toolchain: Toolchain,
    tex_source: str,
    workdir: Path,
    output_stem: str,
) -> RenderArtifacts:
    workdir.mkdir(parents=True, exist_ok=True)

    tex_path = workdir / f"{output_stem}.tex"
    tex_path.write_text(tex_source)

    commands = build_commands(toolchain, tex_path, output_stem)

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
        # Best-effort cropping (no-op if inkscape missing)
        crop_svg_inplace(svg_path)
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
) -> RenderArtifacts:
    """
    Compile TeX and keep artifacts in output_dir.
    Returns paths to .tex/.pdf/.svg and captured stdout/stderr.
    """
    if toolchain_name not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {toolchain_name}")

    tc = TOOLCHAINS[toolchain_name]
    artifacts = _run_toolchain_in_dir(tc, tex_source, Path(output_dir), output_stem)

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
) -> ExecutionResult:
    returncodes = []
    stdout = []
    stderr = []
    svg_text = None

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        tex_file = workdir / f"{output_stem}.tex"
        tex_file.write_text(tex_source)

        commands = build_commands(toolchain, tex_file, output_stem)

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
            crop_svg_inplace(svg_path)
            svg_text = svg_path.read_text()

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
) -> str:
    """
    Compile TeX and return SVG text.

    Diagnostics
    -----------
    If compilation/conversion fails, the raised :class:`RenderError` will include a
    short tail of stderr. For deeper debugging, set ``JUPYTER_TIKZ_KEEP_TEMP=1`` to
    keep the temporary build directory; the exception message will include the path.
    """
    if toolchain_name not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {toolchain_name}")

    tc = TOOLCHAINS[toolchain_name]
    keep = os.environ.get("JUPYTER_TIKZ_KEEP_TEMP") == "1"

    def _stderr_tail(stderr_path: Path, limit_chars: int = 4000) -> str:
        try:
            txt = stderr_path.read_text(errors="replace")
        except Exception:
            return "<stderr unavailable>"
        if len(txt) <= limit_chars:
            return txt
        return txt[-limit_chars:]

    if keep:
        workdir = Path(tempfile.mkdtemp(prefix="jupyter_tikz_"))
        try:
            artifacts = _run_toolchain_in_dir(tc, tex_source, workdir, output_stem)
            if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
                tail = _stderr_tail(artifacts.stderr_path)
                raise RenderError(
                    "Toolchain execution failed. "
                    f"Artifacts kept at: {workdir}. "
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.
"
                    f"---- stderr tail ----
{tail}"
                )
            return artifacts.read_svg()
        except Exception:
            # Do not delete workdir when keep=1
            raise
    else:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = _run_toolchain_in_dir(tc, tex_source, Path(tmp), output_stem)

            if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
                tail = _stderr_tail(artifacts.stderr_path)
                raise RenderError(
                    "Toolchain execution failed.\n"
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                    "---- stderr tail ----\n"
                     f"{tail}"
                )

            return artifacts.read_svg()

