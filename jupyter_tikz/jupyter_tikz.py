"""Compatibility facade for the historical jupyter_tikz module layout."""

from .args import (
    _ARGS,
    _EXTRAS_CONFLITS_ERR,
    _INPUT_TYPE_CONFLIT_ERR,
    _PRINT_CONFLICT_ERR,
    _apply_args,
    _get_arg_params,
    _remove_wrapping_quotes,
)
from .legacy_render import _tail_lines
from .magic import TikZMagics
from .models import ANY_CODE_HASH, TexDocument, TexFragment, code_hash

__all__ = [
    "code_hash",
    "ANY_CODE_HASH",
    "TexDocument",
    "TexFragment",
    "TikZMagics",
    "_ARGS",
    "_get_arg_params",
    "_apply_args",
    "_remove_wrapping_quotes",
    "_EXTRAS_CONFLITS_ERR",
    "_PRINT_CONFLICT_ERR",
    "_INPUT_TYPE_CONFLIT_ERR",
    "_tail_lines",
]
