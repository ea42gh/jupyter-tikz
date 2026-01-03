__author__ = """Lucas Lima Rodrigues"""
__email__ = "lucaslrodri@gmail.com"
__version__ = "0.1.0"

from .jupyter_tikz import _ARGS, TexDocument, TexFragment, TikZMagics, code_hash, ANY_CODE_HASH
from .executor import render_svg, render_svg_with_artifacts, RenderArtifacts, RenderError
from .toolchains import Toolchain, TOOLCHAINS


def load_ipython_extension(ipython):  # pragma: no cover
    ipython.register_magics(TikZMagics)


__all__ = [
    "render_svg",
    "render_svg_with_artifacts",
    "RenderArtifacts",
    "RenderError",
    "Toolchain",
    "TOOLCHAINS",
    "TexDocument",
    "TexFragment",
    "TikZMagics",
    "code_hash",
    "ANY_CODE_HASH",
]