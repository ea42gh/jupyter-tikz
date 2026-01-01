from dataclasses import dataclass
from typing import Sequence


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
    svg_cmd=["pdftocairo", "-svg"],
)

PDFTEX_PDF2SVG = Toolchain(
    name="pdftex_pdf2svg",
    latex_cmd=["latexmk", "-pdf", "-interaction=nonstopmode"],
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
        XELATEX_DVISVGM,
    ]
}

