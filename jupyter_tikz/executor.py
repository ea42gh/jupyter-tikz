from pathlib import Path
from typing import List
from jupyter_tikz.toolchains import Toolchain
from jupyter_tikz.toolchains import TOOLCHAINS
from jupyter_tikz.crop import crop_svg_inplace

import subprocess
import tempfile
#from typing import Sequence


def build_commands(
    toolchain: Toolchain,
    tex_file: Path,
    output_stem: str,
) -> List[List[str]]:
    """
    Return the sequence of command invocations needed for this toolchain.
    Does not execute anything.
    """
    cmds = []

    # LaTeX step
    cmds.append(
        list(toolchain.latex_cmd) + [tex_file.name]
    )

    # SVG conversion step
    if toolchain.needs_pdf:
        pdf = f"{output_stem}.pdf"
        svg = f"{output_stem}.svg"
        cmds.append(
            list(toolchain.svg_cmd) + [pdf, svg]
        )

    elif toolchain.needs_dvi:
        dvi = f"{output_stem}.dvi"
        svg = f"{output_stem}.svg"
        cmds.append(
            list(toolchain.svg_cmd) + [dvi, svg]
        )
    return cmds
# -------------------------------------------------------------------------------------------------------------------


class ExecutionResult:
    def __init__(self, returncodes, stdout, stderr, svg_text):
        self.returncodes = returncodes
        self.stdout = stdout
        self.stderr = stderr
        self.svg_text = svg_text

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

class RenderError(RuntimeError):
    pass


def render_svg(
    tex_source: str,
    *,
    toolchain_name: str = "pdftex_pdftocairo",
    output_stem: str = "output",
) -> str:
    """
    Compile TeX and return SVG text.
    """
    if toolchain_name not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {toolchain_name}")

    tc = TOOLCHAINS[toolchain_name]

    result = run_toolchain(tc, tex_source, output_stem=output_stem)

    if not result.returncodes or result.returncodes[-1] != 0:
        raise RenderError(
            "Toolchain execution failed\n"
            + "\n".join(result.stderr[-1:])
        )

    if result.svg_text is None:
        raise RenderError("SVG output not produced")

    return result.svg_text

