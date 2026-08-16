from jupyter_tikz import (
    InvalidOutputStemError,
    InvalidPathError,
    InvalidToolchainError,
    JupyterTikzError,
    TexDocument,
    TexFragment,
    TikZMagics,
)
from jupyter_tikz.args import _ARGS as ARGS_IN_ARGS
from jupyter_tikz.errors import InvalidOutputStemError as InvalidOutputStemErrorInErrors
from jupyter_tikz.errors import InvalidPathError as InvalidPathErrorInErrors
from jupyter_tikz.errors import InvalidToolchainError as InvalidToolchainErrorInErrors
from jupyter_tikz.errors import JupyterTikzError as JupyterTikzErrorInErrors
from jupyter_tikz.jupyter_tikz import _ARGS as ARGS_IN_FACADE
from jupyter_tikz.magic import TikZMagics as TikZMagicsInMagic
from jupyter_tikz.models import TexDocument as TexDocumentInModels
from jupyter_tikz.models import TexFragment as TexFragmentInModels


def test_facade_exports_point_to_split_modules():
    assert ARGS_IN_FACADE is ARGS_IN_ARGS
    assert TikZMagics is TikZMagicsInMagic
    assert TexDocument is TexDocumentInModels
    assert TexFragment is TexFragmentInModels


def test_facade_exports_typed_errors():
    assert JupyterTikzError is JupyterTikzErrorInErrors
    assert InvalidToolchainError is InvalidToolchainErrorInErrors
    assert InvalidOutputStemError is InvalidOutputStemErrorInErrors
    assert InvalidPathError is InvalidPathErrorInErrors
