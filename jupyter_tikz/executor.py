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
from jupyter_tikz.svg_box import Padding, normalize_padding, apply_padding_to_svg_file, apply_padding_to_svg_text
from jupyter_tikz.toolchains import Toolchain, TOOLCHAINS

# =======================================================================================================
def build_commands(
    toolchain: Toolchain,
    tex_file: Path,
    output_stem: str,
    *,
    crop_mode: Literal["tight", "page", "none"] = "none",
    # NOTE: `enforce_tight_crop` affects only post-processing (Inkscape-based
    # tight-crop) for PDF-based converters. Command construction does not depend
    # on it. We accept it here so callers can pass a consistent option set.
    enforce_tight_crop: bool = False,
    exact_bbox: bool = False,
) -> List[List[str]]:
    """
    Return the sequence of command invocations needed for this toolchain.
    Does not execute anything.
    """
    cmds: List[List[str]] = []

    # LaTeX step
    cmds.append(list(toolchain.latex_cmd) + [tex_file.name])

    # SVG conversion step
    svg_cmd = list(toolchain.svg_cmd)
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
        pdf = f"{output_stem}.pdf"
        svg = f"{output_stem}.svg"
        cmds.append(svg_cmd + [pdf, svg])
    elif toolchain.needs_dvi:
        dvi = f"{output_stem}.dvi"
        svg = f"{output_stem}.svg"
        if svg_cmd and svg_cmd[0] == "dvisvgm":
            # latexmk can produce multi-page DVI; render only the first page.
            # Keep positional arguments as "... <input.dvi> <output.svg>" to satisfy build_commands tests.
            cmds.append(svg_cmd + ["-p", "1", dvi, svg])
        else:
            cmds.append(svg_cmd + [dvi, svg])

    return cmds


# -------------------------------------------------------------------------------------------------------------------
def _resolve_dvisvgm_output_svg(workdir: Path, output_stem: str) -> Path | None:
    """dvisvgm often writes <stem>-<page>.svg (e.g., output-1.svg) even when an
    explicit <stem>.svg is provided. Return a usable SVG path and, if needed,
    rename the first-page output to <stem>.svg for determinism.
    """
    desired = workdir / f"{output_stem}.svg"
    if desired.exists():
        return desired

    cand = workdir / f"{output_stem}-1.svg"
    if cand.exists():
        try:
            cand.replace(desired)
        except Exception:
            shutil.copyfile(cand, desired)
        return desired if desired.exists() else cand

    cands = sorted(workdir.glob(f"{output_stem}-*.svg"))
    if cands:
        first = cands[0]
        try:
            first.replace(desired)
            return desired
        except Exception:
            shutil.copyfile(first, desired)
            return desired if desired.exists() else first

    return None


# -------------------------------------------------------------------------------------------------------------------
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
) -> "RenderArtifacts":
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

    returncodes: List[int] = []
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []

    for cmd in commands:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        returncodes.append(proc.returncode)
        stdout_chunks.append(proc.stdout)
        stderr_chunks.append(proc.stderr)

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
    if not svg_path.exists() and toolchain.svg_cmd and toolchain.svg_cmd[0] == "dvisvgm":
        resolved = _resolve_dvisvgm_output_svg(workdir, output_stem)
        svg_path = resolved if resolved is not None else svg_path

    if svg_path.exists():
        # Tight-crop post-processing is only used for PDF-based converters.
        if enforce_tight_crop and crop_mode == "tight" and (not toolchain.svg_cmd or toolchain.svg_cmd[0] != "dvisvgm"):
            crop_svg_inplace(svg_path)

        # Padding is deterministic and toolchain-agnostic.
        if not padding.is_zero():
            apply_padding_to_svg_file(svg_path, padding)
    else:
        svg_path = None

    return RenderArtifacts(
        workdir=workdir,
        tex_path=tex_path,
        pdf_path=pdf_path,
        svg_path=svg_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        returncodes=returncodes,
    )


# -------------------------------------------------------------------------------------------------------------------
def render_svg_with_artifacts(
    tex_source: str,
    *,
    output_dir: Path,
    toolchain_name: str | None = None,
    output_stem: str = "output",
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    exact_bbox: bool = False,
) -> "RenderArtifacts":
    """
    Compile TeX and keep artifacts in output_dir.
    Returns paths to .tex/.pdf/.svg and captured stdout/stderr.
    """
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")

    tc = TOOLCHAINS[resolved_toolchain]
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    artifacts = _run_toolchain_in_dir(
        tc,
        tex_source,
        Path(output_dir),
        output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
        padding=pad,
    )

    if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
        raise RenderError(
            "Toolchain execution failed. See stderr at: "
            f"{artifacts.stderr_path}"
        )

    if artifacts.svg_path is None:
        raise RenderError("SVG output not produced")

    return artifacts


class ExecutionResult:
    def __init__(self, returncodes, stdout, stderr, svg_text):
        self.returncodes = returncodes
        self.stdout = stdout
        self.stderr = stderr
        self.svg_text = svg_text


# -------------------------------------------------------------------------------------------------------------------
def run_toolchain(
    toolchain: Toolchain,
    tex_source: str,
    output_stem: str = "output",
    *,
    crop: Literal["tight", "page", "none"] | None = None,
    padding=None,
    exact_bbox: bool = False,
) -> ExecutionResult:
    returncodes = []
    stdout = []
    stderr = []
    svg_text = None

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        tex_file = workdir / f"{output_stem}.tex"
        tex_file.write_text(tex_source)

        crop_mode, enforce_tight_crop = resolve_crop_policy(crop, toolchain)
        pad = normalize_padding(padding)
        commands = build_commands(
            toolchain,
            tex_file,
            output_stem,
            crop_mode=crop_mode,
            exact_bbox=exact_bbox,
        )

        for cmd in commands:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            returncodes.append(proc.returncode)
            stdout.append(proc.stdout)
            stderr.append(proc.stderr)

            if proc.returncode != 0:
                break

        svg_path = workdir / f"{output_stem}.svg"
        if not svg_path.exists() and toolchain.svg_cmd and toolchain.svg_cmd[0] == "dvisvgm":
            resolved = _resolve_dvisvgm_output_svg(workdir, output_stem)
            svg_path = resolved if resolved is not None else svg_path

        if svg_path.exists():
            if enforce_tight_crop and crop_mode == "tight" and (not toolchain.svg_cmd or toolchain.svg_cmd[0] != "dvisvgm"):
                crop_svg_inplace(svg_path)
            if not pad.is_zero():
                apply_padding_to_svg_file(svg_path, pad)
            svg_text = svg_path.read_text(errors="replace")

    return ExecutionResult(
        returncodes=returncodes,
        stdout=stdout,
        stderr=stderr,
        svg_text=svg_text,
    )


# =======================================================================================================
class RenderError(RuntimeError):
    pass


# -------------------------------------------------------------------------------------------------------------------
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
        if self.svg_path is not None and self.svg_path.exists():
            return self.svg_path.read_text(errors="replace")

        # dvisvgm commonly writes <stem>-1.svg; if the expected svg_path was not produced,
        # try to locate the first-page output in the same directory.
        if self.svg_path is not None:
            p = self.svg_path
            cand1 = p.with_name(f"{p.stem}-1{p.suffix}")
            if cand1.exists():
                return cand1.read_text(errors="replace")
            cands = sorted(p.parent.glob(f"{p.stem}-*{p.suffix}"))
            if cands:
                return cands[0].read_text(errors="replace")

        raise RenderError("SVG output not produced")


# -------------------------------------------------------------------------------------------------------------------
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
    """
    Compile TeX and return SVG text.

    Diagnostics
    -----------
    If compilation/conversion fails, the raised :class:`RenderError` will include a
    short tail of stderr and the LaTeX .log tail.

    For deeper debugging, set ``JUPYTER_TIKZ_KEEP_TEMP=1`` to keep the temporary
    build directory; the exception message will include the path.
    """
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")

    tc = TOOLCHAINS[resolved_toolchain]
    keep = os.environ.get("JUPYTER_TIKZ_KEEP_TEMP") == "1"
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    def _tail_file(path: Path, *, limit_chars: int = 8000) -> str:
        try:
            if not path.exists():
                return f"<missing: {path.name}>"
            txt = path.read_text(errors="replace")
        except Exception:
            return f"<unreadable: {path.name}>"
        if len(txt) <= limit_chars:
            return txt
        return txt[-limit_chars:]

    def _stderr_tail(stderr_path: Path, limit_chars: int = 4000) -> str:
        return _tail_file(stderr_path, limit_chars=limit_chars)

    def _latex_log_tail(workdir: Path, limit_chars: int = 8000) -> str:
        return _tail_file(workdir / f"{output_stem}.log", limit_chars=limit_chars)

    if keep:
        workdir = Path(tempfile.mkdtemp(prefix="jupyter_tikz_"))
        try:
            artifacts = _run_toolchain_in_dir(
                tc,
                tex_source,
                workdir,
                output_stem,
                crop_mode=crop_mode,
                enforce_tight_crop=enforce_tight_crop,
                exact_bbox=exact_bbox,
                padding=pad,
            )
            if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
                stderr_tail = _stderr_tail(artifacts.stderr_path)
                log_tail = _latex_log_tail(workdir)
                raise RenderError(
                    "Toolchain execution failed. "
                    f"Artifacts kept at: {workdir}. "
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                    "---- stderr tail ----\n"
                    f"{stderr_tail}\n"
                    "---- latex log tail ----\n"
                    f"{log_tail}"
                )
            return artifacts.read_svg()
        except Exception:
            raise
    else:
        if cache and pad.is_zero():
            return _render_base_svg_cached(
                tex_source,
                resolved_toolchain,
                output_stem=output_stem,
                crop_mode=crop_mode,
                enforce_tight_crop=enforce_tight_crop,
                exact_bbox=exact_bbox,
            )
        if cache and (not pad.is_zero()):
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
            workdir = Path(tmp)
            artifacts = _run_toolchain_in_dir(
                tc,
                tex_source,
                workdir,
                output_stem,
                crop_mode=crop_mode,
                enforce_tight_crop=enforce_tight_crop,
                exact_bbox=exact_bbox,
                padding=pad,
            )

            if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
                stderr_tail = _stderr_tail(artifacts.stderr_path)
                log_tail = _latex_log_tail(workdir)
                raise RenderError(
                    "Toolchain execution failed.\n"
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                    "---- stderr tail ----\n"
                    f"{stderr_tail}\n"
                    "---- latex log tail ----\n"
                    f"{log_tail}"
                )

            return artifacts.read_svg()


# ======================================================================================================
# Option resolution + caching

_LEGACY_DEFAULT_TOOLCHAIN = "pdftex_pdftocairo"

_DEFAULT_TOOLCHAIN_CANDIDATES: tuple[str, ...] = (
    "pdftex_pdftocairo",
    "pdftex_pdf2svg",
    "pdftex_dvisvgm",
    "xelatex_pdftocairo",
    "xelatex_pdf2svg",
    "xelatex_dvisvgm",
)

_FAST_DEFAULT_TOOLCHAIN_CANDIDATES: tuple[str, ...] = (
    "pdftex_dvisvgm",
    "xelatex_dvisvgm",
    "pdftex_pdftocairo",
    "pdftex_pdf2svg",
    "xelatex_pdftocairo",
    "xelatex_pdf2svg",
)

_DEFAULT_TOOLCHAIN_OVERRIDE: str | None = None


def set_default_toolchain_name(toolchain_name: str | None) -> None:
    """Set a process-wide default toolchain name (no environment variables required).

    Passing None clears the override.
    """
    global _DEFAULT_TOOLCHAIN_OVERRIDE
    _DEFAULT_TOOLCHAIN_OVERRIDE = toolchain_name


def resolve_toolchain_name(toolchain_name: str | None) -> str:
    """Resolve toolchain_name using overrides and sensible defaults.

    Resolution order:
      1) Explicit argument
      2) Programmatic default override (set_default_toolchain_name)
      3) JUPYTER_TIKZ_DEFAULT_TOOLCHAIN env var
      4) First available candidate with required binaries on PATH
      5) Fallback to the first registered toolchain
    """
    if toolchain_name:
        return toolchain_name

    if _DEFAULT_TOOLCHAIN_OVERRIDE:
        return _DEFAULT_TOOLCHAIN_OVERRIDE

    env = os.environ.get("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN")
    if env:
        return env

    candidates = _DEFAULT_TOOLCHAIN_CANDIDATES
    for cand in candidates:
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
    """Resolve crop mode and whether to enforce tight-cropping.

    Defaults: crop=None -> mode="tight" to preserve historical outputs.
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
    crop_mode, _enforce = resolve_crop_policy(crop, toolchain)
    return crop_mode


_CACHE_MAXSIZE = int(os.environ.get("JUPYTER_TIKZ_CACHE_SIZE", "64"))
_CACHE: "OrderedDict[tuple[str, str, str, bool, bool, bool, str], str]" = OrderedDict()
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
    """Cached render of SVG without padding."""
    tc = TOOLCHAINS[toolchain_name]
    inkscape_variant = bool(
        enforce_tight_crop
        and crop_mode == "tight"
        and (not tc.svg_cmd or tc.svg_cmd[0] != "dvisvgm")
        and (shutil.which("inkscape") is not None)
    )
    tex_key = md5(tex_source.encode("utf-8")).hexdigest()
    key = (toolchain_name, output_stem, crop_mode, enforce_tight_crop, exact_bbox, inkscape_variant, tex_key)

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
        while len(_CACHE) > max(0, _CACHE_MAXSIZE):
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
        workdir = Path(tmp)
        artifacts = _run_toolchain_in_dir(
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
            stderr_tail = artifacts.stderr_path.read_text(errors="replace")[-4000:]
            raise RenderError(
                "Toolchain execution failed.\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{stderr_tail}"
            )
        return artifacts.read_svg()

