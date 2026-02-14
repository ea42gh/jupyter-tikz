from __future__ import annotations

import re
from typing import Any

from IPython.core.magic_arguments import argument

_EXTRAS_CONFLITS_ERR = "You cannot provide `preamble` and (`tex_packages`, `tikz_libraries`, and/or `pgfplots_libraries`) at the same time."
_PRINT_CONFLICT_ERR = (
    "You cannot use `--print-jinja` and `--print-tex` at the same time."
)
_INPUT_TYPE_CONFLIT_ERR = "You cannot use `--implicit-pic`, `--full-document` or/and `-as=<input_type>` at the same time."


_ARGS = {
    "input-type": {
        "short-arg": "as",
        "dest": "input_type",
        "type": str,
        "default": "standalone-document",
        "desc": "Type of the input. Possible values are: `full-document`, `standalone-document` and `tikzpicture`",
        "example": "`-as=full-document`",
    },
    "implicit-pic": {
        "short-arg": "i",
        "dest": "implicit_pic",
        "type": bool,
        "desc": "Alias for `-as=tikzpicture`",
    },
    "full-document": {
        "short-arg": "f",
        "dest": "full_document",
        "type": bool,
        "desc": "Alias for `-as=full-document`",
    },
    "latex-preamble": {
        "short-arg": "p",
        "dest": "latex_preamble",
        "type": str,
        "default": None,
        "desc": "LaTeX preamble to insert before the document",
        "example": '`-p "$preamble"`, with the preamble being an IPython variable',
    },
    "tex-packages": {
        "short-arg": "t",
        "dest": "tex_packages",
        "type": str,
        "default": None,
        "desc": "Comma-separated list of TeX packages",
        "example": "`-t=amsfonts,amsmath`",
    },
    "no-tikz": {
        "short-arg": "nt",
        "dest": "no_tikz",
        "type": bool,
        "desc": "Force to not import the TikZ package",
    },
    "tikz-libraries": {
        "short-arg": "l",
        "dest": "tikz_libraries",
        "type": str,
        "default": None,
        "desc": "Comma-separated list of TikZ libraries",
        "example": "`-l=calc,arrows`",
    },
    "pgfplots-libraries": {
        "short-arg": "lp",
        "dest": "pgfplots_libraries",
        "type": str,
        "default": None,
        "desc": "Comma-separated list of pgfplots libraries",
        "example": "`-pl=groupplots,external`",
    },
    "no-jinja": {
        "short-arg": "nj",
        "dest": "no_jinja",
        "type": bool,
        "desc": "Disable Jinja2 rendering",
    },
    "print-jinja": {
        "short-arg": "pj",
        "dest": "print_jinja",
        "type": bool,
        "desc": "Print the rendered Jinja2 template",
    },
    "print-tex": {
        "short-arg": "pt",
        "dest": "print_tex",
        "type": bool,
        "desc": "Print the full LaTeX document",
    },
    "scale": {
        "short-arg": "sc",
        "dest": "scale",
        "type": float,
        "default": 1.0,
        "desc": "The scale factor to apply to the TikZ diagram",
        "example": "`-sc=0.5`",
    },
    "rasterize": {
        "short-arg": "r",
        "dest": "rasterize",
        "type": bool,
        "desc": "Output a rasterized image (PNG) instead of SVG",
    },
    "dpi": {
        "short-arg": "d",
        "dest": "dpi",
        "type": int,
        "default": 96,
        "desc": "DPI to use when rasterizing the image",
        "example": "`--dpi=300`",
    },
    "gray": {
        "short-arg": "g",
        "dest": "gray",
        "type": bool,
        "desc": "Set grayscale to the rasterized image",
    },
    "full-err": {
        "short-arg": "e",
        "dest": "full_err",
        "type": bool,
        "desc": "Print the full error message when an error occurs",
    },
    "keep-temp": {
        "short-arg": "k",
        "dest": "keep_temp",
        "type": bool,
        "desc": "Keep temporary files",
    },
    "tex-program": {
        "short-arg": "tp",
        "dest": "tex_program",
        "type": str,
        "default": "pdflatex",
        "desc": "TeX program to use for compilation",
        "example": "`-tp=xelatex` or `-tp=lualatex`",
    },
    "tex-args": {
        "short-arg": "ta",
        "dest": "tex_args",
        "type": str,
        "default": None,
        "desc": "Arguments to pass to the TeX program",
        "example": '`-ta "$tex_args_ipython_variable"`',
    },
    "no-compile": {
        "short-arg": "nc",
        "dest": "no_compile",
        "type": bool,
        "desc": "Do not compile the TeX code",
    },
    "save-tikz": {
        "short-arg": "s",
        "dest": "save_tikz",
        "type": str,
        "default": None,
        "desc": "Save the TikZ code to file",
        "example": "`-s filename.tikz`",
    },
    "save-tex": {
        "short-arg": "st",
        "dest": "save_tex",
        "type": str,
        "default": None,
        "desc": "Save full LaTeX code to file",
        "example": "`-st filename.tex`",
    },
    "save-pdf": {
        "short-arg": "sp",
        "dest": "save_pdf",
        "type": str,
        "default": None,
        "desc": "Save PDF file",
        "example": "`-sp filename.pdf`",
    },
    "save-image": {
        "short-arg": "S",
        "dest": "save_image",
        "type": str,
        "default": None,
        "desc": "Save the output image to file",
        "example": "`-S filename.png`",
    },
    "save-var": {
        "short-arg": "sv",
        "dest": "save_var",
        "type": str,
        "default": None,
        "desc": "Save the TikZ or LaTeX code to an IPython variable",
        "example": "`-sv my_var`",
    },
}


def _get_arg_params(arg: str) -> tuple[tuple[str, str], dict[str, Any]]:
    def get_arg_help(arg: str) -> str:
        help_text = _ARGS[arg]["desc"].replace("<br>", " ")
        if _ARGS[arg].get("example"):
            help_text += f", e.g., {_ARGS[arg]['example']}"
        if _ARGS[arg].get("default"):
            help_text += (
                f". Defaults to `-{_ARGS[arg]['short-arg']}={_ARGS[arg]['default']}`"
            )
        help_text += "."
        return help_text

    args = (f"-{_ARGS[arg]['short-arg']}", f"--{arg}")
    kwargs = {"dest": _ARGS[arg]["dest"]}
    if _ARGS[arg]["type"] == bool:
        kwargs["action"] = "store_true"
        kwargs["default"] = False
    elif _ARGS[arg]["type"] == str:
        kwargs["default"] = _ARGS[arg]["default"]
    else:
        kwargs["type"] = _ARGS[arg]["type"]
        kwargs["default"] = _ARGS[arg]["default"]
    kwargs["help"] = get_arg_help(arg)
    return args, kwargs


def _apply_args():
    def decorator(magic_command):
        for arg in reversed(_ARGS.keys()):
            args, kwargs = _get_arg_params(arg)
            magic_command = argument(*args, **kwargs)(magic_command)
        return magic_command

    return decorator


def _remove_wrapping_quotes(text: str) -> str:
    pattern = re.compile(r'^"(.*)"$', re.DOTALL)
    return pattern.sub(r"\1", text)
