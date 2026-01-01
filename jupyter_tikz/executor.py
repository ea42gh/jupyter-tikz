from pathlib import Path
from typing import List
from jupyter_tikz.toolchains import Toolchain

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
    def __init__(self, returncodes, stdout, stderr, workdir):
        self.returncodes = returncodes
        self.stdout = stdout
        self.stderr = stderr
        self.workdir = workdir


def run_toolchain(
    toolchain: Toolchain,
    tex_source: str,
    output_stem: str = "output",
) -> ExecutionResult:
    """
    Execute the toolchain in a temporary directory.
    """
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        tex_file = workdir / f"{output_stem}.tex"
        tex_file.write_text(tex_source)

        commands = build_commands(toolchain, tex_file, output_stem)

        returncodes = []
        stdout = []
        stderr = []

        for cmd in commands:
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            returncodes.append(proc.returncode)
            stdout.append(proc.stdout)
            stderr.append(proc.stderr)

            if proc.returncode != 0:
                break

        return ExecutionResult(
            returncodes=returncodes,
            stdout=stdout,
            stderr=stderr,
            workdir=workdir,
        )


