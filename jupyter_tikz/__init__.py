__author__ = """Lucas Lima Rodrigues"""
__email__ = "lucaslrodri@gmail.com"
__version__ = "0.1.0"

from .jupyter_tikz import _ARGS, TexDocument, TexFragment, TikZMagics
from .executor import render_svg, RenderError
from .toolchains import Toolchain, TOOLCHAINS


def load_ipython_extension(ipython):  # pragma: no cover
    ipython.register_magics(TikZMagics)


__all__ = [
    "render_svg",
    "RenderError",
    "Toolchain",
    "TOOLCHAINS",
    "TexDocument",
    "TexFragment",
    "TikZMagics",
]

