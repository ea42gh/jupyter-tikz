from __future__ import annotations

from pathlib import Path
from typing import Literal

from jupyter_tikz.toolchains import Toolchain


def build_commands(
    toolchain: Toolchain,
    tex_file: Path,
    output_stem: str,
    *,
    crop_mode: Literal["tight", "page", "none"] = "none",
    # NOTE: `enforce_tight_crop` affects only post-processing (Inkscape-based
    # tight-crop). Command construction does not depend on it. We accept it here
    # so callers can pass a consistent option set.
    enforce_tight_crop: bool = False,
    exact_bbox: bool = False,
) -> list[list[str]]:
    """Return the sequence of command invocations needed for this toolchain.

    This is a pure function used by tests to validate wiring.
    """

    cmds: list[list[str]] = []

    # LaTeX step
    cmds.append(list(toolchain.latex_cmd) + [tex_file.name])

    # SVG conversion step
    base_svg_cmd = list(toolchain.svg_cmd)

    # dvisvgm has its own bbox and output flags.
    if base_svg_cmd and base_svg_cmd[0] == "dvisvgm":
        svg_cmd = list(base_svg_cmd)
        if crop_mode == "tight":
            svg_cmd += ["--bbox=min"]
            if exact_bbox:
                svg_cmd += ["--exact-bbox"]
        elif crop_mode == "page":
            svg_cmd += ["--bbox=papersize"]
        elif crop_mode == "none":
            pass

        # Ensure deterministic output name and single-page selection.
        svg_cmd += [
            f"--output={output_stem}.svg",
            "--page=1",
            f"{output_stem}{toolchain.latex_output_ext}",
        ]
        cmds.append(svg_cmd)
        return cmds

    # PDF-based converters: positional input/output.
    if toolchain.needs_pdf:
        pdf = f"{output_stem}{toolchain.latex_output_ext}"
        svg = f"{output_stem}.svg"
        cmds.append(list(base_svg_cmd) + [pdf, svg])
        return cmds

    # Non-dvisvgm DVI converters (currently none in registry, but keep for completeness)
    if toolchain.needs_dvi:
        dvi = f"{output_stem}{toolchain.latex_output_ext}"
        svg = f"{output_stem}.svg"
        cmds.append(list(base_svg_cmd) + [dvi, svg])
        return cmds

    return cmds