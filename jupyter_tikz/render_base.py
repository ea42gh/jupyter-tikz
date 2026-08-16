from __future__ import annotations

import shutil
import tempfile
from hashlib import md5
from pathlib import Path
from typing import Literal

from jupyter_tikz import cache as _cache
from jupyter_tikz.diagnostics import format_toolchain_failure
from jupyter_tikz.engine import run_toolchain_in_dir
from jupyter_tikz.render_types import RenderError
from jupyter_tikz.svg_box import Padding
from jupyter_tikz.toolchains import TOOLCHAINS


def render_base_svg_cached(
    tex_source: str,
    toolchain_name: str,
    *,
    output_stem: str,
    crop_mode: Literal["tight", "page", "none"],
    enforce_tight_crop: bool,
    exact_bbox: bool,
) -> str:
    """Cached render of SVG without padding.

    Padding is intentionally excluded from the cache key so that callers can
    apply arbitrary per-side padding cheaply without re-running LaTeX.
    """
    inkscape_variant = bool(
        enforce_tight_crop
        and crop_mode == "tight"
        and (shutil.which("inkscape") is not None)
    )
    tex_key = md5(tex_source.encode("utf-8")).hexdigest()
    key = (
        toolchain_name,
        output_stem,
        crop_mode,
        enforce_tight_crop,
        exact_bbox,
        inkscape_variant,
        tex_key,
    )
    return _cache.get_or_render_base_svg(
        key,
        lambda: render_base_svg_uncached(
            tex_source,
            toolchain_name,
            output_stem=output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
        ),
    )


def render_base_svg_uncached(
    tex_source: str,
    toolchain_name: str,
    *,
    output_stem: str,
    crop_mode: Literal["tight", "page", "none"],
    enforce_tight_crop: bool,
    exact_bbox: bool,
) -> str:
    tc = TOOLCHAINS[toolchain_name]
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        artifacts = run_toolchain_in_dir(
            tc,
            tex_source,
            workdir,
            output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=Padding(),
        )
        if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
            raise RenderError(
                format_toolchain_failure(
                    artifacts,
                    workdir=workdir,
                    output_stem=output_stem,
                )
            )
        return artifacts.read_svg()


_render_base_svg_cached = render_base_svg_cached
_render_base_svg_uncached = render_base_svg_uncached