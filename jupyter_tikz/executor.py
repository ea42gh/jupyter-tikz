from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Union

from jupyter_tikz import artifacts as _artifacts
from jupyter_tikz import cache as _cache
from jupyter_tikz import policy as _policy
from jupyter_tikz import render_base as _render_base
from jupyter_tikz.canvas_frame import (
    apply_canvas_frame_to_svg_file,
    apply_canvas_frame_to_svg_text,
)
from jupyter_tikz.diagnostics import format_toolchain_failure
from jupyter_tikz.engine import _run_toolchain_in_dir
from jupyter_tikz.errors import InvalidToolchainError
from jupyter_tikz.naming import validate_output_stem
from jupyter_tikz.render_types import ExecutionResult, RenderArtifacts, RenderError
from jupyter_tikz.svg_box import Padding, apply_padding_to_svg_text, normalize_padding
from jupyter_tikz.svg_normalize import strip_svg_xml_declaration
from jupyter_tikz.toolchains import TOOLCHAINS, Toolchain

# from typing import Sequence

resolve_crop_mode = _policy.resolve_crop_mode
resolve_crop_policy = _policy.resolve_crop_policy
resolve_toolchain_name = _policy.resolve_toolchain_name
set_default_toolchain_name = _policy.set_default_toolchain_name
clear_render_cache = _cache.clear_render_cache

@dataclass(frozen=True)
class _ResolvedRenderOptions:
    toolchain_name: str
    toolchain: Toolchain
    output_stem: str
    crop_mode: Literal["tight", "page", "none"]
    enforce_tight_crop: bool
    padding: Padding


def _resolve_render_options(
    *,
    toolchain_name: str | None,
    output_stem: str,
    crop: Literal["tight", "page", "none"] | None,
    padding,
) -> _ResolvedRenderOptions:
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    resolved_stem = validate_output_stem(output_stem)
    if resolved_toolchain not in TOOLCHAINS:
        raise InvalidToolchainError(f"Unknown toolchain: {resolved_toolchain}")

    toolchain = TOOLCHAINS[resolved_toolchain]
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, toolchain)
    return _ResolvedRenderOptions(
        toolchain_name=resolved_toolchain,
        toolchain=toolchain,
        output_stem=resolved_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        padding=normalize_padding(padding),
    )


def _raise_for_bad_artifacts(
    artifacts: RenderArtifacts,
    *,
    workdir: Path,
    output_stem: str,
) -> None:
    if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
        raise RenderError(
            format_toolchain_failure(
                artifacts,
                workdir=workdir,
                output_stem=output_stem,
            )
        )

    if artifacts.svg_path is None:
        raise RenderError(f"SVG output not produced.\nArtifacts kept at: {workdir}.")


def _render_cached_svg(
    tex_source: str,
    *,
    opts: _ResolvedRenderOptions,
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
    opts = _resolve_render_options(
        toolchain_name=toolchain_name,
        output_stem=output_stem,
        crop=crop,
        padding=padding,
    )
    outdir = Path(output_dir)

    artifacts = _run_toolchain_in_dir(
        opts.toolchain,
        tex_source,
        outdir,
        opts.output_stem,
        crop_mode=opts.crop_mode,
        enforce_tight_crop=opts.enforce_tight_crop,
        exact_bbox=exact_bbox,
        padding=opts.padding,
    )

    _raise_for_bad_artifacts(
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
        artifacts = _run_toolchain_in_dir(
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
    opts = _resolve_render_options(
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
        artifacts = _run_toolchain_in_dir(
            opts.toolchain,
            tex_source,
            workdir,
            stem,
            crop_mode=opts.crop_mode,
            enforce_tight_crop=opts.enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=opts.padding,
        )

        _raise_for_bad_artifacts(artifacts, workdir=workdir, output_stem=stem)


        if frame and artifacts.svg_path is not None:
            apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

        # Read raw SVG here and apply the strip policy once via _maybe_strip().
        svg = artifacts.read_svg(strip_xml_declaration=False)
        ok = True
        return _maybe_strip(svg)
    finally:
        if cleanup_on_success and ok:
            shutil.rmtree(workdir, ignore_errors=True)



