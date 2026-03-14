from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Literal, Sequence

import jinja2
from IPython import display
from IPython.display import SVG, Image

from .naming import validate_output_stem
from .save_paths import resolve_save_destination


def _tail_lines(msg: str, max_lines: int = 20) -> str:
    if max_lines <= 0:
        return msg
    return "\n".join(msg.splitlines()[-max_lines:])


def run_command(
    tex_obj,
    command: str | Sequence[str],
    full_err: bool = False,
    **kwargs,
) -> int:
    if "working_dir" in kwargs and "cwd" not in kwargs:
        kwargs["cwd"] = kwargs.pop("working_dir")

    if isinstance(command, str):
        cmd = shlex.split(command)
    else:
        cmd = [str(c) for c in command]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            **kwargs,
        )
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result.returncode != 0:
        err_msg = result.stderr if result.stderr else result.stdout
        if not full_err:
            err_msg = _tail_lines(err_msg, max_lines=20)
        print(err_msg, file=sys.stderr)
    return result.returncode


def save_artifact(
    tex_obj,
    dest: str,
    ext: Literal["tikz", "tex", "png", "svg", "pdf"],
) -> None:
    dest_path = resolve_save_destination(dest, ext)

    if ext == "tikz":
        if not tex_obj.tikz_code:
            raise ValueError("No TikZ code to save.")
        dest_path.write_text(tex_obj.tikz_code, encoding="utf-8")
    else:
        stem = str(getattr(tex_obj, "_active_output_stem", tex_obj._hex_hash))
        Path(stem).with_suffix(f".{ext}").replace(dest_path)


def render_jinja(tex_obj, ns) -> None:
    fs_loader = jinja2.FileSystemLoader(os.getcwd())

    tmpl_env = jinja2.Environment(
        loader=fs_loader,
        block_start_string="(**",
        block_end_string="**)",
        variable_start_string="(*",
        variable_end_string="*)",
        comment_start_string="(~",
        comment_end_string="~)",
    )

    tmpl = tmpl_env.from_string(tex_obj._code)
    tex_obj._code = tmpl.render(**ns)


def run_latex(
    tex_obj,
    *,
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
    stem = validate_output_stem(output_stem or tex_obj._hex_hash)
    tex_obj._active_output_stem = stem
    try:
        tex_path = Path().resolve() / f"{stem}.tex"
        tex_path.write_text(tex_obj.full_latex, encoding="utf-8")

        tex_command = [tex_program]
        if tex_args:
            tex_command.extend(shlex.split(tex_args))
        tex_command.append(str(tex_path))

        res = tex_obj._run_command(tex_command, full_err)
        if res != 0:
            tex_obj._clearup_latex_garbage(keep_temp)
            return None

        image_format = "svg" if not rasterize else "png"

        if os.environ.get("JUPYTER_TIKZ_PDFTOCAIROPATH"):
            pdftocairo_path = os.environ.get("JUPYTER_TIKZ_PDFTOCAIROPATH")
        else:
            pdftocairo_path = "pdftocairo"

        pdftocairo_command = [str(pdftocairo_path), f"-{image_format}"]
        if rasterize:
            pdftocairo_command.extend(
                ["-singlefile", f"-{'gray' if grayscale else 'transp'}", "-r", str(dpi)]
            )

        pdftocairo_command.extend(
            [
                str(tex_path.with_suffix(".pdf")),
                (
                    str(tex_path.with_suffix(".svg"))
                    if not rasterize
                    else str(tex_path.parent / tex_path.stem)
                ),
            ]
        )
        res = tex_obj._run_command(pdftocairo_command, full_err)

        if res != 0:
            tex_obj._clearup_latex_garbage(keep_temp)
            return None

        image = (
            display.Image(tex_path.with_suffix(".png"))
            if rasterize
            else display.SVG(tex_path.with_suffix(".svg"))
        )

        if save_image:
            tex_obj._save(save_image, image_format)
        if save_tex:
            tex_obj._save(save_tex, "tex")
        if save_pdf:
            tex_obj._save(save_pdf, "pdf")
        if save_tikz and tex_obj.tikz_code:
            tex_obj._save(save_tikz, "tikz")

        tex_obj._clearup_latex_garbage(keep_temp)
        return image
    finally:
        tex_obj._clearup_latex_garbage(keep_temp)
        if hasattr(tex_obj, "_active_output_stem"):
            delattr(tex_obj, "_active_output_stem")
