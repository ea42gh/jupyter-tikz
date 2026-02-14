import shutil
from dataclasses import dataclass
from typing import Sequence

from .errors import InvalidToolchainError


@dataclass(frozen=True)
class Toolchain:
    name: str
    latex_cmd: Sequence[str]
    svg_cmd: Sequence[str]
    needs_pdf: bool = True
    needs_dvi: bool = False


# --- Core toolchains ---

PDFTEX_PDFTOCAIRO = Toolchain(
    name="pdftex_pdftocairo",
    latex_cmd=["latexmk", "-pdf", "-interaction=nonstopmode"],
    # NOTE: Some pdftocairo builds emit numbered outputs (e.g. output-1.svg)
    # when given a prefix; we always pass an explicit output filename
    # (output.svg) via build_commands, and the executor also contains a
    # suffix-tolerant finder as a fallback.
    svg_cmd=["pdftocairo", "-svg"],
)

PDFTEX_PDF2SVG = Toolchain(
    name="pdftex_pdf2svg",
    latex_cmd=["latexmk", "-pdf", "-interaction=nonstopmode"],
    svg_cmd=["pdf2svg"],
)

PDFTEX_DVISVGM = Toolchain(
    name="pdftex_dvisvgm",
    latex_cmd=["latexmk", "-dvi", "-interaction=nonstopmode"],
    svg_cmd=["dvisvgm", "--no-fonts"],
    needs_pdf=False,
    needs_dvi=True,
)

XELATEX_PDFTOCAIRO = Toolchain(
    name="xelatex_pdftocairo",
    latex_cmd=["latexmk", "-xelatex", "-interaction=nonstopmode"],
    # See PDFTEX_PDFTOCAIRO note on output naming.
    svg_cmd=["pdftocairo", "-svg"],
)

XELATEX_PDF2SVG = Toolchain(
    name="xelatex_pdf2svg",
    latex_cmd=["latexmk", "-xelatex", "-interaction=nonstopmode"],
    svg_cmd=["pdf2svg"],
)

XELATEX_DVISVGM = Toolchain(
    name="xelatex_dvisvgm",
    latex_cmd=["latexmk", "-xelatex", "-interaction=nonstopmode", "-dvi"],
    svg_cmd=["dvisvgm", "--no-fonts"],
    needs_pdf=False,
    needs_dvi=True,
)


# --- Registry ---

TOOLCHAINS = {
    tc.name: tc
    for tc in [
        PDFTEX_PDFTOCAIRO,
        PDFTEX_PDF2SVG,
        PDFTEX_DVISVGM,
        XELATEX_PDFTOCAIRO,
        XELATEX_PDF2SVG,
        XELATEX_DVISVGM,
    ]
}


def check_toolchain(toolchain_name: str) -> dict[str, object]:
    """Return availability diagnostics for one configured toolchain."""
    tc = TOOLCHAINS.get(toolchain_name)
    if tc is None:
        raise InvalidToolchainError(
            f"Unknown toolchain: {toolchain_name}. "
            f"Available: {', '.join(sorted(TOOLCHAINS.keys()))}"
        )

    latex_bin = str(tc.latex_cmd[0]) if tc.latex_cmd else ""
    svg_bin = str(tc.svg_cmd[0]) if tc.svg_cmd else ""
    latex_path = shutil.which(latex_bin) if latex_bin else None
    svg_path = shutil.which(svg_bin) if svg_bin else None

    return {
        "name": tc.name,
        "latex_bin": latex_bin,
        "latex_path": latex_path,
        "svg_bin": svg_bin,
        "svg_path": svg_path,
        "available": bool(latex_path and svg_path),
    }


def check_toolchains() -> dict[str, dict[str, object]]:
    """Return availability diagnostics for all configured toolchains."""
    return {name: check_toolchain(name) for name in sorted(TOOLCHAINS.keys())}
