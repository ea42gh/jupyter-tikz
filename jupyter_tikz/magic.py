from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from IPython import display
from IPython.core.magic import Magics, line_cell_magic, magics_class, needs_local_scope
from IPython.core.magic_arguments import argument, magic_arguments, parse_argstring
from IPython.display import Image, SVG

from .args import (
    _EXTRAS_CONFLITS_ERR,
    _INPUT_TYPE_CONFLIT_ERR,
    _PRINT_CONFLICT_ERR,
    _apply_args,
    _remove_wrapping_quotes,
)
from .executor import RenderError, render_svg_with_artifacts
from .legacy_render import _tail_lines
from .models import TexDocument, TexFragment


def _resolve_save_dest(dest: str, ext: Literal["tikz", "tex", "png", "svg", "pdf"]) -> Path:
    dest_path = Path(dest)
    if os.environ.get("JUPYTER_TIKZ_SAVEDIR"):
        dest_path = Path(str(os.environ.get("JUPYTER_TIKZ_SAVEDIR"))) / dest_path
    dest_path = dest_path.resolve()
    if dest_path.suffix != f".{ext}":
        dest_path = dest_path.with_suffix(dest_path.suffix + f".{ext}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    return dest_path


@magics_class
class TikZMagics(Magics):
    def _get_input_type(self, input_type: str) -> str | None:
        valid_input_types = ["full-document", "standalone-document", "tikzpicture"]
        input_type = input_type.lower()
        input_type_len = len(input_type)

        for index, valid_input_type in enumerate(valid_input_types):
            if input_type == valid_input_type[:input_type_len]:
                return valid_input_types[index]

        return None

    def _resolve_executor_toolchain(self) -> str | None:
        tex_program = (self.args.get("tex_program") or "pdflatex").lower().strip()
        if self.args.get("tex_args"):
            return None
        if tex_program == "pdflatex":
            return "pdftex_pdftocairo"
        if tex_program == "xelatex":
            return "xelatex_pdftocairo"
        return None

    @staticmethod
    def _print_err(msg: str, full_err: bool) -> None:
        err_msg = msg
        if not full_err:
            err_msg = _tail_lines(err_msg, max_lines=20)
        print(err_msg, file=sys.stderr)

    def _rasterize_from_pdf(
        self,
        *,
        pdf_path: Path,
        png_path: Path,
        dpi: int,
        grayscale: bool,
        full_err: bool,
    ) -> bool:
        pdftocairo_path = os.environ.get("JUPYTER_TIKZ_PDFTOCAIROPATH") or "pdftocairo"
        cmd = [
            pdftocairo_path,
            "-png",
            "-singlefile",
            f"-{'gray' if grayscale else 'transp'}",
            "-r",
            str(dpi),
            str(pdf_path),
            str(png_path.with_suffix("")),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            err_msg = proc.stderr if proc.stderr else proc.stdout
            self._print_err(err_msg, full_err)
            return False
        return True

    def _render_with_executor(self) -> Image | SVG | None:
        toolchain_name = self._resolve_executor_toolchain()
        if toolchain_name is None:
            return self.tex_obj.run_latex(
                tex_program=self.args["tex_program"],
                tex_args=self.args["tex_args"],
                rasterize=self.args["rasterize"],
                full_err=self.args["full_err"],
                keep_temp=self.args["keep_temp"],
                save_tikz=self.args["save_tikz"],
                save_tex=self.args["save_tex"],
                save_pdf=self.args["save_pdf"],
                save_image=self.args["save_image"],
                dpi=self.args["dpi"],
                grayscale=self.args["gray"],
            )

        keep_temp = bool(self.args["keep_temp"])
        output_stem = self.tex_obj._hex_hash

        def _run_in(workdir: Path) -> Image | SVG | None:
            try:
                artifacts = render_svg_with_artifacts(
                    self.tex_obj.full_latex,
                    output_dir=workdir,
                    toolchain_name=toolchain_name,
                    output_stem=output_stem,
                )
            except (RenderError, ValueError) as exc:
                self._print_err(str(exc), self.args["full_err"])
                return None

            if self.args["save_tex"]:
                shutil.copy2(
                    artifacts.tex_path,
                    _resolve_save_dest(self.args["save_tex"], "tex"),
                )

            if self.args["save_pdf"] and artifacts.pdf_path is not None:
                shutil.copy2(
                    artifacts.pdf_path,
                    _resolve_save_dest(self.args["save_pdf"], "pdf"),
                )

            if self.args["save_tikz"] and self.tex_obj.tikz_code:
                _resolve_save_dest(self.args["save_tikz"], "tikz").write_text(
                    self.tex_obj.tikz_code,
                    encoding="utf-8",
                )

            if self.args["rasterize"]:
                if artifacts.pdf_path is None:
                    self._print_err("PDF output not produced.", self.args["full_err"])
                    return None

                png_path = workdir / f"{output_stem}.png"
                ok = self._rasterize_from_pdf(
                    pdf_path=artifacts.pdf_path,
                    png_path=png_path,
                    dpi=self.args["dpi"],
                    grayscale=self.args["gray"],
                    full_err=self.args["full_err"],
                )
                if not ok:
                    return None

                if self.args["save_image"]:
                    shutil.copy2(
                        png_path,
                        _resolve_save_dest(self.args["save_image"], "png"),
                    )
                return display.Image(filename=str(png_path))

            svg_text = artifacts.read_svg(strip_xml_declaration=False)
            if self.args["save_image"]:
                shutil.copy2(
                    artifacts.svg_path,
                    _resolve_save_dest(self.args["save_image"], "svg"),
                )
            return display.SVG(data=svg_text)

        if keep_temp:
            return _run_in(Path().resolve())
        with tempfile.TemporaryDirectory(prefix="jupyter_tikz_") as tmp:
            return _run_in(Path(tmp))

    @line_cell_magic
    @magic_arguments()
    @_apply_args()
    @argument("code", nargs="?", help="the variable in IPython with the Tex/TikZ code")
    @needs_local_scope
    def tikz(self, line, cell: str | None = None, local_ns=None) -> Image | SVG | None:
        self.args: dict = vars(parse_argstring(self.tikz, line))

        for key, value in self.args.items():
            if not isinstance(value, str):
                continue
            self.args[key] = _remove_wrapping_quotes(value)

        if self.args["latex_preamble"] and (
            self.args["tex_packages"]
            or self.args["tikz_libraries"]
            or self.args["pgfplots_libraries"]
        ):
            print(_EXTRAS_CONFLITS_ERR, file=sys.stderr)
            return

        if (self.args["implicit_pic"] and self.args["full_document"]) or (
            (self.args["implicit_pic"] or self.args["full_document"])
            and self.args["input_type"] != "standalone-document"
        ):
            print(_INPUT_TYPE_CONFLIT_ERR, file=sys.stderr)
            return

        if self.args["print_jinja"] and self.args["print_tex"]:
            print(_PRINT_CONFLICT_ERR, file=sys.stderr)
            return

        if self.args["implicit_pic"]:
            self.input_type = "tikzpicture"
        elif self.args["full_document"]:
            self.input_type = "full-document"
        else:
            self.input_type = self._get_input_type(self.args["input_type"])
        if self.input_type is None:
            print(
                f'`{self.args["input_type"]}` is not a valid input type.',
                "Valid input types are `full-document`, `standalone-document`, or `tikzpicture`.",
                file=sys.stderr,
            )
            return

        self.src = cell or ""
        local_ns = local_ns or {}

        if cell is None:
            if self.args["code"] is None:
                print('Use "%tikz?" for help', file=sys.stderr)
                return

            if self.args["code"] not in local_ns:
                self.src = self.args["code"]
            else:
                self.src = local_ns[self.args["code"]]

        if self.input_type == "full-document":
            self.tex_obj = TexDocument(
                self.src, no_jinja=self.args["no_jinja"], ns=local_ns
            )
        else:
            implicit_tikzpicture = self.input_type == "tikzpicture"
            self.tex_obj = TexFragment(
                self.src,
                implicit_tikzpicture=implicit_tikzpicture,
                preamble=self.args["latex_preamble"],
                tex_packages=self.args["tex_packages"],
                no_tikz=self.args["no_tikz"],
                tikz_libraries=self.args["tikz_libraries"],
                pgfplots_libraries=self.args["pgfplots_libraries"],
                scale=self.args["scale"],
                no_jinja=self.args["no_jinja"],
                ns=local_ns,
            )

        if self.args["print_jinja"]:
            print(self.tex_obj)
        if self.args["print_tex"]:
            print(self.tex_obj.full_latex)

        image = None
        if not self.args["no_compile"]:
            image = self._render_with_executor()
            if image is None:
                return None

        if self.args["save_var"]:
            local_ns[self.args["save_var"]] = str(self.tex_obj)

        return image
