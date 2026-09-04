from __future__ import annotations

import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional, Union

from IPython import display
from IPython.display import SVG, Image

from jupyter_tikz import artifacts as _artifacts
from jupyter_tikz import cache as _cache
from jupyter_tikz import policy as _policy
from jupyter_tikz import render_base as _render_base
from jupyter_tikz import toolchains as _toolchains
from jupyter_tikz.canvas_frame import (
    apply_canvas_frame_to_svg_file,
    apply_canvas_frame_to_svg_text,
)
from jupyter_tikz.engine import run_toolchain_in_dir
from jupyter_tikz.naming import validate_output_stem
from jupyter_tikz.render_options import ResolvedRenderOptions, resolve_render_options
from jupyter_tikz.render_types import (  # noqa: F401
    ExecutionResult,
    RenderArtifacts,
    RenderError,
)
from jupyter_tikz.svg_box import apply_padding_to_svg_text, normalize_padding
from jupyter_tikz.svg_normalize import strip_svg_xml_declaration
from jupyter_tikz.toolchains import Toolchain

resolve_crop_mode = _policy.resolve_crop_mode
resolve_crop_policy = _policy.resolve_crop_policy
resolve_toolchain_name = _policy.resolve_toolchain_name
set_default_toolchain_name = _policy.set_default_toolchain_name
clear_render_cache = _cache.clear_render_cache
TOOLCHAINS = _toolchains.TOOLCHAINS


def _render_cached_svg(
    tex_source: str,
    *,
    opts: ResolvedRenderOptions,
    exact_bbox: bool,
    frame,
) -> str:
    svg = _render_base.render_base_svg_cached(
        tex_source,
        opts.toolchain_name,
        output_stem=opts.output_stem,
        crop_mode=opts.crop_mode,
        enforce_tight_crop=opts.enforce_tight_crop,
        exact_bbox=exact_bbox,
    )
    if not opts.padding.is_zero():
        svg = apply_padding_to_svg_text(svg, opts.padding)
    if frame:
        svg = apply_canvas_frame_to_svg_text(svg, frame)
    return svg

# -------------------------------------------------------------------------------------------------------------------
def render_svg_with_artifacts(
    tex_source: str,
    *,
    output_dir: Path,
    toolchain_name: str | None = None,
    output_stem: str = "output",
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    frame=None,
    exact_bbox: bool = False,
) -> RenderArtifacts:
    """
    Compile TeX and keep artifacts in output_dir.
    Returns paths to .tex/.pdf/.svg and captured stdout/stderr.
    """
    opts = resolve_render_options(
        toolchain_name=toolchain_name,
        output_stem=output_stem,
        crop=crop,
        padding=padding,
    )
    outdir = Path(output_dir)

    artifacts = run_toolchain_in_dir(
        opts.toolchain,
        tex_source,
        outdir,
        opts.output_stem,
        crop_mode=opts.crop_mode,
        enforce_tight_crop=opts.enforce_tight_crop,
        exact_bbox=exact_bbox,
        padding=opts.padding,
    )

    _artifacts.raise_for_bad_artifacts(
        artifacts,
        workdir=outdir,
        output_stem=opts.output_stem,
    )

    if frame and artifacts.svg_path is not None:
        apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

    return artifacts


# -------------------------------------------------------------------------------------------------------------------
def run_toolchain(
    toolchain: Toolchain,
    tex_source: str,
    output_stem: str = "output",
    *,
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    frame=None,
    exact_bbox: bool = False,
    strip_xml_declaration: bool = True,
) -> ExecutionResult:
    output_stem = validate_output_stem(output_stem)
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, toolchain)
    pad = normalize_padding(padding)
    svg_text = None

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        artifacts = run_toolchain_in_dir(
            toolchain,
            tex_source,
            workdir,
            output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=pad,
        )

        if artifacts.svg_path is not None and artifacts.svg_path.exists():
            svg_text = artifacts.read_svg(strip_xml_declaration=strip_xml_declaration)
            if frame and svg_text is not None:
                svg_text = apply_canvas_frame_to_svg_text(svg_text, frame)

        stdout = [artifacts.stdout_path.read_text(errors="replace")]
        stderr = [artifacts.stderr_path.read_text(errors="replace")]
        returncodes = artifacts.returncodes

    return ExecutionResult(
        returncodes=returncodes,
        stdout=stdout,
        stderr=stderr,
        svg_text=svg_text,
    )


# -------------------------------------------------------------------------------------------------------------------
def render_svg(
    tex_source: str,
    *,
    toolchain_name: str | None = None,
    output_stem: str = "output",
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    frame=None,
    exact_bbox: bool = False,
    artifacts_path: Optional[Union[str, os.PathLike]] = None,
    artifacts_prefix: Optional[Union[str, os.PathLike]] = None,
    cache: bool = True,
    strip_xml_declaration: bool = True,
) -> str:
    """
    Compile TeX and return SVG text.

    Diagnostics
    -----------
    If compilation/conversion fails, the raised :class:`RenderError` will include a
    short tail of stderr and the LaTeX .log tail.

    For deeper debugging, set ``JUPYTER_TIKZ_KEEP_TEMP=1`` to keep the temporary
    build directory; the exception message will include the path.
    """
    opts = resolve_render_options(
        toolchain_name=toolchain_name,
        output_stem=output_stem,
        crop=crop,
        padding=padding,
    )

    # When the caller asks to persist artifacts, caching would bypass writing
    # .tex/.svg/.stdout/.stderr files.
    if artifacts_path is not None or artifacts_prefix is not None:
        cache = False

    def _maybe_strip(svg_text: str) -> str:
        return (
            strip_svg_xml_declaration(svg_text) if strip_xml_declaration else svg_text
        )

    # In-memory cache only applies when we are not asked to write artifacts.
    if cache and artifacts_path is None and artifacts_prefix is None:
        return _maybe_strip(
            _render_cached_svg(
                tex_source,
                opts=opts,
                exact_bbox=exact_bbox,
                frame=frame,
            )
        )

    workdir, stem, cleanup_on_success = _artifacts.resolve_artifacts_target(
        tex_source,
        output_stem=opts.output_stem,
        artifacts_path=artifacts_path,
        artifacts_prefix=artifacts_prefix,
    )

    ok = False
    try:
        artifacts = run_toolchain_in_dir(
            opts.toolchain,
            tex_source,
            workdir,
            stem,
            crop_mode=opts.crop_mode,
            enforce_tight_crop=opts.enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=opts.padding,
        )

        _artifacts.raise_for_bad_artifacts(artifacts, workdir=workdir, output_stem=stem)


        if frame and artifacts.svg_path is not None:
            apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

        # Read raw SVG here and apply the strip policy once via _maybe_strip().
        svg = artifacts.read_svg(strip_xml_declaration=False)
        ok = True
        return _maybe_strip(svg)
    finally:
        if cleanup_on_success and ok:
            shutil.rmtree(workdir, ignore_errors=True)





def render_document(
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
