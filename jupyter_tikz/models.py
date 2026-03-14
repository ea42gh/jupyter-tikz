from __future__ import annotations

import re
from hashlib import md5
from pathlib import Path
from string import Template
from textwrap import dedent, indent
from typing import Any, Literal, Sequence

from IPython.display import SVG, Image

from .args import _EXTRAS_CONFLITS_ERR
from .legacy_render import render_jinja, run_command, run_latex, save_artifact


def code_hash(code: str) -> str:
    return md5(code.encode()).hexdigest()


ANY_CODE_HASH = code_hash("any code")


class TexDocument:
    def __init__(
        self, code: str, no_jinja: bool = False, ns: dict[str, Any] | None = None
    ):
        self._code: str = code.strip()
        self._no_jinja: bool = no_jinja
        if not ns:
            ns = {}

        if not self._no_jinja:
            self._render_jinja(ns)

    @property
    def full_latex(self) -> str:
        return self._code

    @property
    def tikz_code(self) -> str | None:
        pattern = r"^\s*\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}"
        match = re.search(pattern, self.full_latex, re.DOTALL | re.MULTILINE)
        if match:
            return dedent(match.group(0))
        return None

    @staticmethod
    def _arg_head(arg, limit=60) -> str:
        if type(arg) == str:
            arg = arg.strip()
            arg = f"{arg[:limit]}..." if len(arg) > limit else arg
            arg = str(repr(arg.strip()))
        else:
            arg = str(arg)
        return arg

    @property
    def _hex_hash(self) -> str:
        return code_hash(self.full_latex)

    def __repr__(self) -> str:
        params_dict = self.__dict__
        if "scale" in params_dict.keys():
            if params_dict["scale"] == 1.0:
                del params_dict["scale"]

        params = ", ".join(
            [
                f'{k if k != "_no_jinja" else "no_jinja"}={self._arg_head(v)}'
                for k, v in params_dict.items()
                if k not in ["_code", "full_latex", "tikz_code", "ns"] and v
            ]
        )
        if params:
            params = ", " + params
        return f"{self.__class__.__name__}({self._arg_head(self._code)}{params})"

    def __str__(self) -> str:
        return self._code

    def _clearup_latex_garbage(self, keep_temp) -> None:
        if not keep_temp:
            stem = str(getattr(self, "_active_output_stem", self._hex_hash))
            files = Path().glob(f"{stem}.*")
            for file in files:
                if file.exists():
                    file.unlink()

    def _run_command(
        self, command: str | Sequence[str], full_err: bool = False, **kwargs
    ) -> int:
        return run_command(self, command, full_err, **kwargs)

    def _save(
        self, dest: str, ext: Literal["tikz", "tex", "png", "svg", "pdf"]
    ) -> None:
        return save_artifact(self, dest, ext)

    def _render_jinja(self, ns) -> None:
        return render_jinja(self, ns)

    def run_latex(
        self,
        tex_program: str = "pdflatex",
        tex_args: str | None = None,
        rasterize: bool = False,
        full_err: bool = False,
        keep_temp: bool = False,
        output_stem: str | None = None,
        save_image: str | None = None,
        dpi: int = 96,
        grayscale: bool = False,
        save_tex: str | None = None,
        save_tikz: str | None = None,
        save_pdf: str | None = None,
    ) -> Image | SVG | None:
        return run_latex(
            self,
            tex_program=tex_program,
            tex_args=tex_args,
            rasterize=rasterize,
            full_err=full_err,
            keep_temp=keep_temp,
            output_stem=output_stem,
            save_image=save_image,
            dpi=dpi,
            grayscale=grayscale,
            save_tex=save_tex,
            save_tikz=save_tikz,
            save_pdf=save_pdf,
        )


class TexFragment(TexDocument):
    TMPL = Template(
        "\\documentclass{standalone}\n"
        + "$preamble"
        + "\\begin{document}\n"
        + "$scale_begin"
        + "$tikzpicture_begin"
        + "$code"
        + "$tikzpicture_end"
        + "$scale_end"
        + "\\end{document}"
    )
    TMPL_STANDALONE_PREAMBLE = Template(
        "$graphicx_package"
        + "$tikz_package"
        + "$tex_packages"
        + "$tikz_libraries"
        + "$pgfplots_libraries"
    )

    def __init__(
        self,
        code: str,
        implicit_tikzpicture: bool = False,
        scale: float = 1.0,
        preamble: str | None = None,
        tex_packages: str | None = None,
        tikz_libraries: str | None = None,
        pgfplots_libraries: str | None = None,
        no_tikz: bool = False,
        **kwargs,
    ):
        if preamble and (tex_packages or tikz_libraries or pgfplots_libraries):
            raise ValueError(_EXTRAS_CONFLITS_ERR)

        self.template = "tikzpicture" if implicit_tikzpicture else "standalone-document"
        self.scale = scale or 1.0
        if preamble:
            self.preamble = preamble.strip() + "\n"
        else:
            self.preamble = self._build_standalone_preamble(
                tex_packages, tikz_libraries, pgfplots_libraries, no_tikz
            )

        super().__init__(code, **kwargs)

    def _build_standalone_preamble(
        self,
        tex_packages: str | None = None,
        tikz_libraries: str | None = None,
        pgfplots_libraries: str | None = None,
        no_tikz: bool = False,
    ) -> str:
        tikz_package = "" if no_tikz else "\\usepackage{tikz}\n"

        graphicx_package = "" if self.scale == 1 else "\\usepackage{graphicx}\n"

        tex_packages = "\\usepackage{%s}\n" % tex_packages if tex_packages else ""
        tikz_libraries = (
            "\\usetikzlibrary{%s}\n" % tikz_libraries if tikz_libraries else ""
        )
        pgfplots_libraries = (
            "\\usepgfplotslibrary{%s}\n" % pgfplots_libraries
            if pgfplots_libraries
            else ""
        )

        return self.TMPL_STANDALONE_PREAMBLE.substitute(
            graphicx_package=graphicx_package,
            tikz_package=tikz_package,
            tex_packages=tex_packages,
            tikz_libraries=tikz_libraries,
            pgfplots_libraries=pgfplots_libraries,
        )

    @property
    def full_latex(self) -> str:
        if self.scale != 1:
            scale_begin = indent("\\scalebox{" + str(self.scale) + "}{\n", " " * 4)
            scale_end = indent("}\n", " " * 4)
        else:
            scale_begin = ""
            scale_end = ""

        if self.template == "tikzpicture":
            tikzpicture_begin = indent("\\begin{tikzpicture}\n", " " * 4)
            tikzpicture_end = indent("\\end{tikzpicture}\n", " " * 4)
            code_indent = " " * 8
        else:
            tikzpicture_begin = ""
            tikzpicture_end = ""
            code_indent = " " * 4

        code = indent(self._code, code_indent) + "\n" if self._code else ""

        return self.TMPL.substitute(
            preamble=self.preamble,
            scale_begin=scale_begin,
            tikzpicture_begin=tikzpicture_begin,
            code=code,
            tikzpicture_end=tikzpicture_end,
            scale_end=scale_end,
        )
