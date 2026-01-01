from pathlib import Path
from typing import List
from jupyter_tikz.toolchains import Toolchain


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
