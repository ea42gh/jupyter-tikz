__author__ = """Lucas Lima Rodrigues"""
__email__ = "lucaslrodri@gmail.com"
__version__ = "0.5.8"

from .errors import (
    InvalidOutputStemError,
    InvalidPathError,
    InvalidToolchainError,
    JupyterTikzError,
)
from .executor import (
    RenderArtifacts,
    RenderError,
    clear_render_cache,
    render_svg,
    render_svg_with_artifacts,
)
from .jupyter_tikz import _ARGS, TexDocument, TexFragment, TikZMagics
from .toolchains import TOOLCHAINS, Toolchain, check_toolchain, check_toolchains


def load_ipython_extension(ipython):  # pragma: no cover
    ipython.register_magics(TikZMagics)


__all__ = [
    "render_svg",
    "render_svg_with_artifacts",
    "RenderArtifacts",
    "RenderError",
    "clear_render_cache",
    "Toolchain",
    "TOOLCHAINS",
    "check_toolchain",
    "check_toolchains",
    "JupyterTikzError",
    "InvalidToolchainError",
    "InvalidOutputStemError",
    "InvalidPathError",
    "_ARGS",
    "TexDocument",
    "TexFragment",
    "TikZMagics",
]
