from jupyter_tikz.args import _ARGS as ARGS_IN_ARGS
from jupyter_tikz.jupyter_tikz import _ARGS as ARGS_IN_FACADE
from jupyter_tikz.magic import TikZMagics as TikZMagicsInMagic
from jupyter_tikz.models import TexDocument as TexDocumentInModels
from jupyter_tikz.models import TexFragment as TexFragmentInModels
from jupyter_tikz import TikZMagics, TexDocument, TexFragment


def test_facade_exports_point_to_split_modules():
    assert ARGS_IN_FACADE is ARGS_IN_ARGS
    assert TikZMagics is TikZMagicsInMagic
    assert TexDocument is TexDocumentInModels
    assert TexFragment is TexFragmentInModels
