from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import md5
from pathlib import Path
from typing import List, Literal

from jupyter_tikz.crop import crop_svg_inplace
from jupyter_tikz.svg_box import (
    Padding,
    normalize_padding,
    apply_padding_to_svg_file,
    apply_padding_to_svg_text,
)
from jupyter_tikz.toolchains import Toolchain, TOOLCHAINS


def build_commands(
    toolchain: Toolchain,
    tex_file: Path,
    output_stem: str,
    *,
    crop_mode: Literal["tight", "page", "none"] = "none",
    # affects only post-processing (Inkscape crop) for PDF-based converters
    # but accepted for a uniform signature
    enforce_tight_crop: bool = False,
    exact_bbox: bool = False,
) -> List[List[str]]:
    """
    Build the sequence of shell command invocations for a given toolchain.
    Pure function: does not execute anything.
    """
    cmds: List[List[str]] = []

    latex_cmd = list(toolchain.latex_cmd) + [tex_file.name]
    cmds.append(latex_cmd)

    svg_cmd = list(toolchain.svg_cmd)

    # dvisvgm supports bbox flags for cropping.
    if svg_cmd and svg_cmd[0] == "dvisvgm":
        if crop_mode == "tight":
            svg_cmd += ["--bbox=min"]
            if exact_bbox:
                svg_cmd += ["--exact-bbox"]
        elif crop_mode == "page":
            svg_cmd += ["--bbox=papersize"]
        elif crop_mode == "none":
            pass

    if toolchain.needs_pdf:
        cmds.append(svg_cmd + [f"{output_stem}.pdf", f"{output_stem}.svg"])
    elif toolchain.needs_dvi:
        cmds.append(svg_cmd + [f"{output_stem}.dvi", f"{output_stem}.svg"])
    else:
        raise ValueError("Toolchain must require either PDF or DVI output.")

    return cmds


@dataclass(frozen=True)
class TexDocument:
    tex: str
    toolchain_name: str = "pdftex_pdftocairo"

    def render_svg(
        self,
        *,
        crop: Literal["tight", "page", "none"] | None = None,
        padding=None,
        exact_bbox: bool = False,
        cache: bool = True,
    ) -> str:
        return render_svg(
            self.tex,
            toolchain_name=self.toolchain_name,
            crop=crop,
            padding=padding,
            exact_bbox=exact_bbox,
            cache=cache,
        )


@dataclass(frozen=True)
class RenderArtifacts:
    workdir: Path
    tex_path: Path
    pdf_path: Path | None
    svg_path: Path | None
    stdout_path: Path
    stderr_path: Path
    returncodes: List[int]

    def read_svg(self) -> str:
        if not self.svg_path or not self.svg_path.exists():
            raise RenderError("SVG output missing.")
        return self.svg_path.read_text(errors="replace")


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    returncodes: List[int]
    stdout: str
    stderr: str


def _run_toolchain_in_dir(
    toolchain: Toolchain,
    tex_source: str,
    workdir: Path,
    output_stem: str,
    *,
    crop_mode: Literal["tight", "page", "none"],
    enforce_tight_crop: bool,
    exact_bbox: bool,
    padding: Padding,
) -> RenderArtifacts:
    workdir.mkdir(parents=True, exist_ok=True)

    tex_path = workdir / f"{output_stem}.tex"
    tex_path.write_text(tex_source)

    commands = build_commands(
        toolchain,
        tex_path,
        output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
    )

    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    returncodes: List[int] = []

    for cmd in commands:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_chunks.append(proc.stdout or "")
        stderr_chunks.append(proc.stderr or "")
        returncodes.append(proc.returncode)
        if proc.returncode != 0:
            break

    stdout_path = workdir / f"{output_stem}.stdout.txt"
    stderr_path = workdir / f"{output_stem}.stderr.txt"
    stdout_path.write_text("".join(stdout_chunks))
    stderr_path.write_text("".join(stderr_chunks))

    pdf_path = workdir / f"{output_stem}.pdf"
    if not pdf_path.exists():
        pdf_path = None

    svg_path = workdir / f"{output_stem}.svg"
    if not svg_path.exists():
        svg_path = None
    else:
        # For PDF-based toolchains, enforce tight cropping via Inkscape (best-effort).
        # For dvisvgm toolchains, the crop_mode flags already handled cropping.
        if (
            enforce_tight_crop
            and crop_mode == "tight"
            and (not toolchain.svg_cmd or toolchain.svg_cmd[0] != "dvisvgm")
        ):
            crop_svg_inplace(svg_path)

        # Deterministic per-side padding (toolchain-agnostic).
        if not padding.is_zero():
            apply_padding_to_svg_file(svg_path, padding)

    return RenderArtifacts(
        workdir=workdir,
        tex_path=tex_path,
        pdf_path=pdf_path,
        svg_path=svg_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncodes=returncodes,
    )


def render_svg_with_artifacts(
    tex_source: str,
    *,
    output_dir: Path,
    toolchain_name: str | None = None,
    output_stem: str = "output",
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    exact_bbox: bool = False,
) -> RenderArtifacts:
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")
    tc = TOOLCHAINS[resolved_toolchain]

    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    return _run_toolchain_in_dir(
        tc,
        tex_source,
        output_dir,
        output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
        padding=pad,
    )


def run_toolchain(
    toolchain: Toolchain,
    tex_source: str,
    workdir: Path | None = None,
    output_stem: str = "output",
    *,
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    exact_bbox: bool = False,
) -> ExecutionResult:
    """
    Execute a toolchain and return stdout/stderr as strings.

    If workdir is None, a temporary directory is used and removed automatically.
    """
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, toolchain)
    pad = normalize_padding(padding)

    if workdir is None:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = _run_toolchain_in_dir(
                toolchain,
                tex_source,
                Path(tmp),
                output_stem,
                crop_mode=crop_mode,
                enforce_tight_crop=enforce_tight_crop,
                exact_bbox=exact_bbox,
                padding=pad,
            )
            return ExecutionResult(
                returncodes=artifacts.returncodes,
                stdout=artifacts.stdout_path.read_text(errors="replace"),
                stderr=artifacts.stderr_path.read_text(errors="replace"),
            )

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
    return ExecutionResult(
        returncodes=artifacts.returncodes,
        stdout=artifacts.stdout_path.read_text(errors="replace"),
        stderr=artifacts.stderr_path.read_text(errors="replace"),
    )


def render_svg(
    tex_source: str,
    *,
    toolchain_name: str | None = None,
    output_stem: str = "output",
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    exact_bbox: bool = False,
    cache: bool = True,
) -> str:
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")
    tc = TOOLCHAINS[resolved_toolchain]

    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    if cache:
        base = _render_base_svg_cached(
            tex_source,
            resolved_toolchain,
            output_stem=output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
        )
        return apply_padding_to_svg_text(base, pad)

    with tempfile.TemporaryDirectory() as tmp:
        artifacts = _run_toolchain_in_dir(
            tc,
            tex_source,
            Path(tmp),
            output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=pad,
        )
        if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
            stderr_tail = artifacts.stderr_path.read_text(errors="replace")[-4000:]
            raise RenderError(
                "Toolchain execution failed.\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{stderr_tail}"
            )
        return artifacts.read_svg()


_DEFAULT_TOOLCHAIN_CANDIDATES: tuple[str, ...] = (
    "pdftex_pdftocairo",
    "pdftex_pdf2svg",
    "pdftex_dvisvgm",
    "xelatex_pdftocairo",
    "xelatex_pdf2svg",
    "xelatex_dvisvgm",
)

_DEFAULT_TOOLCHAIN_OVERRIDE: str | None = None


def set_default_toolchain_name(name: str | None) -> None:
    global _DEFAULT_TOOLCHAIN_OVERRIDE
    _DEFAULT_TOOLCHAIN_OVERRIDE = name


def resolve_toolchain_name(toolchain_name: str | None) -> str:
    if toolchain_name:
        return toolchain_name

    if _DEFAULT_TOOLCHAIN_OVERRIDE:
        return _DEFAULT_TOOLCHAIN_OVERRIDE

    env = os.environ.get("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN")
    if env:
        return env

    for cand in _DEFAULT_TOOLCHAIN_CANDIDATES:
        tc = TOOLCHAINS.get(cand)
        if not tc:
            continue
        if shutil.which(tc.latex_cmd[0]) is None:
            continue
        if shutil.which(tc.svg_cmd[0]) is None:
            continue
        return cand

    return next(iter(TOOLCHAINS.keys()))


def resolve_crop_policy(
    crop: Literal["tight", "page", "none"] | None,
    toolchain: Toolchain,
) -> tuple[Literal["tight", "page", "none"], bool]:
    """
    Returns (mode, enforce_tight_crop).

    Test-aligned semantics:
    - crop=None defaults to mode="tight".
    - For PDF toolchains, enforce=True iff mode == "tight".
    - For dvisvgm toolchains, enforce=False (cropping is handled by dvisvgm flags).
    """
    if crop in ("tight", "page", "none"):
        mode = crop
    else:
        mode = "tight"

    is_dvisvgm = bool(toolchain.svg_cmd) and toolchain.svg_cmd[0] == "dvisvgm"
    if is_dvisvgm:
        return (mode, False)

    return (mode, mode == "tight")


def resolve_crop_mode(
    crop: Literal["tight", "page", "none"] | None,
    toolchain: Toolchain,
) -> Literal["tight", "page", "none"]:
    mode, _ = resolve_crop_policy(crop, toolchain)
    return mode


_CACHE_MAXSIZE = int(os.environ.get("JUPYTER_TIKZ_CACHE_SIZE", "64"))
_CACHE: "OrderedDict[tuple[str, str, str, bool, bool, str], str]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_render_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _render_base_svg_cached(
    tex_source: str,
    toolchain_name: str,
    *,
    output_stem: str,
    crop_mode: Literal["tight", "page", "none"],
    enforce_tight_crop: bool,
    exact_bbox: bool,
) -> str:
    tex_key = md5(tex_source.encode("utf-8")).hexdigest()
    key = (toolchain_name, output_stem, crop_mode, enforce_tight_crop, exact_bbox, tex_key)

    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]

    svg = _render_base_svg_uncached(
        tex_source,
        toolchain_name,
        output_stem=output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
    )

    with _CACHE_LOCK:
        _CACHE[key] = svg
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAXSIZE:
            _CACHE.popitem(last=False)

    return svg


def _render_base_svg_uncached(
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
        artifacts = _run_toolchain_in_dir(
            tc,
            tex_source,
            Path(tmp),
            output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=Padding(),
        )
        if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
            stderr_tail = artifacts.stderr_path.read_text(errors="replace")[-4000:]
            raise RenderError(
                "Toolchain execution failed.\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{stderr_tail}"
            )
        return artifacts.read_svg()

