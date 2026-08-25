from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from jupyter_tikz import policy as _policy
from jupyter_tikz.errors import InvalidToolchainError
from jupyter_tikz.naming import validate_output_stem
from jupyter_tikz.svg_box import Padding, normalize_padding
from jupyter_tikz.toolchains import TOOLCHAINS, Toolchain


@dataclass(frozen=True)
class ResolvedRenderOptions:
    toolchain_name: str
    toolchain: Toolchain
    output_stem: str
    crop_mode: Literal["tight", "page", "none"]
    enforce_tight_crop: bool
    padding: Padding


def resolve_render_options(
    *,
    toolchain_name: str | None,
    output_stem: str,
    crop: Literal["tight", "page", "none"] | None,
    padding,
) -> ResolvedRenderOptions:
    resolved_toolchain = _policy.resolve_toolchain_name(toolchain_name)
    resolved_stem = validate_output_stem(output_stem)
    if resolved_toolchain not in TOOLCHAINS:
        raise InvalidToolchainError(f"Unknown toolchain: {resolved_toolchain}")

    toolchain = TOOLCHAINS[resolved_toolchain]
    crop_mode, enforce_tight_crop = _policy.resolve_crop_policy(crop, toolchain)
    return ResolvedRenderOptions(
        toolchain_name=resolved_toolchain,
        toolchain=toolchain,
        output_stem=resolved_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        padding=normalize_padding(padding),
    )
