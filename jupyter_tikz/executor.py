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
from typing import List, Literal, Optional, Tuple, Union

from jupyter_tikz.artifacts import (
    _canonicalize_svg_output_path,
    _find_svg_output_path,
)
from jupyter_tikz.canvas_frame import (
    apply_canvas_frame_to_svg_file,
    apply_canvas_frame_to_svg_text,
)
from jupyter_tikz.commands import build_commands
from jupyter_tikz.crop import crop_svg_inplace
from jupyter_tikz.diagnostics import format_toolchain_failure
from jupyter_tikz.errors import InvalidToolchainError
from jupyter_tikz.naming import validate_output_stem
from jupyter_tikz.paths import validate_user_output_path
from jupyter_tikz.svg_box import (
    Padding,
    apply_padding_to_svg_file,
    apply_padding_to_svg_text,
    normalize_padding,
)
from jupyter_tikz.svg_normalize import strip_svg_xml_declaration
from jupyter_tikz.toolchains import TOOLCHAINS, Toolchain

# from typing import Sequence


# =======================================================================================================
def _build_subprocess_env(*, source_cwd: Path | None = None) -> dict[str, str]:
    """Build subprocess env with a TeX search path that includes caller CWD.

    By default we keep executor builds isolated in a temp workdir, but still
    allow relative TeX inputs (e.g. ``\\input{grid.tikz}``, PGFPlots
    ``table {data.tsv}``) from the notebook/project directory.

    Set ``JUPYTER_TIKZ_DISABLE_CWD_TEXINPUTS=1`` to opt out of this behavior.
    """

    env = os.environ.copy()
    if _env_truthy("JUPYTER_TIKZ_DISABLE_CWD_TEXINPUTS"):
        return env

    cwd = str((source_cwd or Path.cwd()).resolve())
    texinputs = env.get("TEXINPUTS", "")
    prefix = os.pathsep.join([".", cwd])
    if texinputs:
        env["TEXINPUTS"] = os.pathsep.join([prefix, texinputs])
    else:
        # Keep the trailing separator so TeX also searches its default paths.
        env["TEXINPUTS"] = prefix + os.pathsep
    return env


_LATEX_RERUN_MARKERS: tuple[str, ...] = (
    "Label(s) may have changed. Rerun to get cross-references right.",
    "Rerun to get citations correct.",
    "Rerun to get outlines right",
    "rerunfilecheck Warning: File",
    "There were undefined references.",
)


def _file_digest(path: Path) -> str | None:
    try:
        if not path.exists():
            return None
        return md5(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _latex_requests_rerun(stdout: str, stderr: str, log_path: Path) -> bool:
    haystacks = [stdout or "", stderr or ""]
    try:
        if log_path.exists():
            haystacks.append(log_path.read_text(errors="replace"))
    except Exception:
        pass
    return any(marker in hay for hay in haystacks for marker in _LATEX_RERUN_MARKERS)


def _run_latex_passes(
    toolchain: Toolchain,
    tex_path: Path,
    *,
    workdir: Path,
    env: dict[str, str],
) -> tuple[List[int], List[str], List[str]]:
    returncodes: List[int] = []
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    aux_path = workdir / f"{tex_path.stem}.aux"
    log_path = workdir / f"{tex_path.stem}.log"
    prev_aux_digest: str | None = None

    for pass_num in range(max(1, int(toolchain.max_passes))):
        proc = subprocess.run(
            list(toolchain.latex_cmd) + [tex_path.name],
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        returncodes.append(proc.returncode)
        stdout_chunks.append(proc.stdout)
        stderr_chunks.append(proc.stderr)

        if proc.returncode != 0:
            break

        aux_digest = _file_digest(aux_path)
        rerun = _latex_requests_rerun(proc.stdout, proc.stderr, log_path)
        if pass_num + 1 >= max(1, int(toolchain.max_passes)):
            break
        if not rerun and aux_digest == prev_aux_digest:
            break
        prev_aux_digest = aux_digest

    return returncodes, stdout_chunks, stderr_chunks


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

    tex_source = tex_source.replace("ᵀ", "^{T}")

    tex_path = workdir / f"{output_stem}.tex"
    tex_path.write_text(tex_source, encoding="utf-8", newline="\n")

    commands = build_commands(
        toolchain,
        tex_path,
        output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
    )

    run_env = _build_subprocess_env()
    returncodes, stdout_chunks, stderr_chunks = _run_latex_passes(
        toolchain,
        tex_path,
        workdir=workdir,
        env=run_env,
    )

    if not returncodes or returncodes[-1] == 0:
        for cmd in commands[1:]:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),
                env=run_env,
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

    pdf_candidate = workdir / f"{output_stem}.pdf"
    pdf_path: Path | None = pdf_candidate if pdf_candidate.exists() else None

    svg_path = _canonicalize_svg_output_path(
        workdir,
        output_stem,
        _find_svg_output_path(workdir, output_stem),
    )
    if svg_path is not None and svg_path.exists():
        if enforce_tight_crop and crop_mode == "tight":
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
    frame=None,
    exact_bbox: bool = False,
) -> RenderArtifacts:
    """
    Compile TeX and keep artifacts in output_dir.
    Returns paths to .tex/.pdf/.svg and captured stdout/stderr.
    """
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    output_stem = validate_output_stem(output_stem)
    if resolved_toolchain not in TOOLCHAINS:
        raise InvalidToolchainError(f"Unknown toolchain: {resolved_toolchain}")

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
            format_toolchain_failure(
                artifacts,
                workdir=Path(output_dir),
                output_stem=output_stem,
            )
        )

    if artifacts.svg_path is None:
        raise RenderError(
            f"SVG output not produced.\nArtifacts kept at: {Path(output_dir)}."
        )

    if frame and artifacts.svg_path is not None:
        apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

    return artifacts


def _resolve_artifacts_target(
    tex_source: str,
    *,
    output_stem: str,
    artifacts_path: Optional[Union[str, os.PathLike]] = None,
    artifacts_prefix: Optional[Union[str, os.PathLike]] = None,
) -> Tuple[Path, str, bool]:
    """Resolve (workdir, stem, cleanup_on_success) for render_svg.

    Rules
    -----
    - If ``artifacts_path`` is None: create a temp directory and clean it up on success.
      On failure the temp directory is *kept* and the exception message includes its path.
    - If ``artifacts_prefix`` is set: treat it as an explicit file prefix and
      write artifacts as ``{prefix}.tex/.svg/...``.
    - If ``artifacts_path`` is set: treat it as an artifacts directory (created
      if needed) and use a unique stem ``{output_stem}-{md5(tex)[:8]}``.
    """

    safe_stem = validate_output_stem(output_stem)

    if artifacts_path is None:
        if artifacts_prefix is not None:
            p = validate_user_output_path(
                artifacts_prefix, field_name="artifacts_prefix"
            )
            validate_output_stem(p.name)
            p.parent.mkdir(parents=True, exist_ok=True)
            return p.parent, p.name, False
        workdir = Path(tempfile.mkdtemp(prefix="jupyter_tikz_"))
        cleanup_on_success = os.environ.get("JUPYTER_TIKZ_KEEP_TEMP") != "1"
        return workdir, safe_stem, cleanup_on_success

    if artifacts_prefix is not None:
        raise ValueError("Use only one of artifacts_path or artifacts_prefix")

    p = validate_user_output_path(artifacts_path, field_name="artifacts_path")
    p.mkdir(parents=True, exist_ok=True)
    h8 = md5(tex_source.encode("utf-8")).hexdigest()[:8]
    return p, f"{safe_stem}-{h8}", False


@dataclass(frozen=True)
class ExecutionResult:
    returncodes: List[int]
    stdout: List[str]
    stderr: List[str]
    svg_text: str | None

    @property
    def stdout_text(self) -> str:
        return "".join(self.stdout)

    @property
    def stderr_text(self) -> str:
        return "".join(self.stderr)


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
        run_env = _build_subprocess_env()
        latex_rcs, latex_stdout, latex_stderr = _run_latex_passes(
            toolchain,
            tex_file,
            workdir=workdir,
            env=run_env,
        )
        returncodes.extend(latex_rcs)
        stdout.extend(latex_stdout)
        stderr.extend(latex_stderr)
        commands = commands[1:] if (not returncodes or returncodes[-1] == 0) else []

        for cmd in commands:
            proc = subprocess.run(
                cmd,
                cwd=str(workdir),  # ← str() is correct
                env=run_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            returncodes.append(proc.returncode)
            stdout.append(proc.stdout)
            stderr.append(proc.stderr)

            if proc.returncode != 0:
                break

        svg_path = _canonicalize_svg_output_path(
            workdir,
            output_stem,
            _find_svg_output_path(workdir, output_stem),
        )
        if svg_path is not None and svg_path.exists():
            if enforce_tight_crop and crop_mode == "tight":
                crop_svg_inplace(svg_path)
            if not pad.is_zero():
                apply_padding_to_svg_file(svg_path, pad)
            svg_text = svg_path.read_text(errors="replace")
            if strip_xml_declaration and svg_text is not None:
                svg_text = strip_svg_xml_declaration(svg_text)
            if frame and svg_text is not None:
                svg_text = apply_canvas_frame_to_svg_text(svg_text, frame)

    # ← temp directory is cleaned up here, safely
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

    def read_svg(self, *, strip_xml_declaration: bool = True) -> str:
        if self.svg_path is None or not self.svg_path.exists():
            raise RenderError("SVG output not produced")
        txt = self.svg_path.read_text(errors="replace")
        return strip_svg_xml_declaration(txt) if strip_xml_declaration else txt


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
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    output_stem = validate_output_stem(output_stem)
    if resolved_toolchain not in TOOLCHAINS:
        raise InvalidToolchainError(f"Unknown toolchain: {resolved_toolchain}")

    tc = TOOLCHAINS[resolved_toolchain]
    # When the caller asks to persist artifacts, caching would bypass writing
    # .tex/.svg/.stdout/.stderr files.
    if artifacts_path is not None or artifacts_prefix is not None:
        cache = False
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    def _maybe_strip(svg_text: str) -> str:
        return (
            strip_svg_xml_declaration(svg_text) if strip_xml_declaration else svg_text
        )

    # In-memory cache only applies when we are not asked to write artifacts.
    if cache and artifacts_path is None and artifacts_prefix is None and pad.is_zero():
        base = _render_base_svg_cached(
            tex_source,
            resolved_toolchain,
            output_stem=output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
        )
        if frame:
            base = apply_canvas_frame_to_svg_text(base, frame)
        return _maybe_strip(base)

    if (
        cache
        and artifacts_path is None
        and artifacts_prefix is None
        and (not pad.is_zero())
    ):
        base = _render_base_svg_cached(
            tex_source,
            resolved_toolchain,
            output_stem=output_stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
        )
        svg = apply_padding_to_svg_text(base, pad)
        if frame:
            svg = apply_canvas_frame_to_svg_text(svg, frame)
        return _maybe_strip(svg)

    workdir, stem, cleanup_on_success = _resolve_artifacts_target(
        tex_source,
        output_stem=output_stem,
        artifacts_path=artifacts_path,
        artifacts_prefix=artifacts_prefix,
    )

    ok = False
    try:
        artifacts = _run_toolchain_in_dir(
            tc,
            tex_source,
            workdir,
            stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=pad,
        )

        if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
            raise RenderError(
                format_toolchain_failure(artifacts, workdir=workdir, output_stem=stem)
            )

        if artifacts.svg_path is None:
            raise RenderError(
                f"SVG output not produced.\nArtifacts kept at: {workdir}."
            )

        if frame and artifacts.svg_path is not None:
            apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

        # Read raw SVG here and apply the strip policy once via _maybe_strip().
        svg = artifacts.read_svg(strip_xml_declaration=False)
        ok = True
        return _maybe_strip(svg)
    finally:
        if cleanup_on_success and ok:
            shutil.rmtree(workdir, ignore_errors=True)


# ======================================================================================================
# Option resolution + caching

_LEGACY_DEFAULT_TOOLCHAIN = "pdftex_pdftocairo"

_DEFAULT_TOOLCHAIN_CANDIDATES: tuple[str, ...] = (
    # Keep legacy behaviour stable unless the user explicitly opts into "fast defaults".
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


def _env_truthy(name: str) -> bool:
    """Return True if an environment variable is set to a truthy value.

    Accepted truthy values (case-insensitive): 1, true, yes, on.
    """
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "on"}


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

    candidates = (
        _FAST_DEFAULT_TOOLCHAIN_CANDIDATES
        if _env_truthy("JUPYTER_TIKZ_FAST_DEFAULTS")
        else _DEFAULT_TOOLCHAIN_CANDIDATES
    )
    for cand in candidates:
        tc = TOOLCHAINS.get(cand)
        if not tc:
            continue
        if shutil.which(tc.latex_cmd[0]) is None:
            continue
        if shutil.which(tc.svg_cmd[0]) is None:
            continue
        return cand

    # Last resort: stable fallback.
    return next(iter(TOOLCHAINS.keys()))


def resolve_crop_policy(
    crop: Literal["tight", "page", "none"] | None,
    toolchain: Toolchain,
) -> tuple[Literal["tight", "page", "none"], bool]:
    """Resolve crop mode and whether to enforce tight-cropping.

    Semantics
    ---------
    - For *dvisvgm* toolchains, tight/page/none are first implemented via dvisvgm
      flags.
    - For every toolchain, tight-cropping is then enforced via Inkscape when
      ``mode == "tight"`` and Inkscape is available.

    Defaults
    --------
    ``crop=None`` defaults to ``mode="tight"`` to preserve historical outputs.
    """
    if crop in ("tight", "page", "none"):
        mode = crop
    else:
        mode = "tight"

    return (mode, mode == "tight")


def resolve_crop_mode(
    crop: Literal["tight", "page", "none"] | None,
    toolchain: Toolchain,
) -> Literal["tight", "page", "none"]:
    """Resolve crop mode only.

    This preserves the legacy default of returning ``"tight"`` when crop is not
    specified, while allowing the execution layer to distinguish between a
    default (soft) tight-crop and an explicit request (enforced) tight-crop.
    """
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
            raise RenderError(
                format_toolchain_failure(
                    artifacts,
                    workdir=workdir,
                    output_stem=output_stem,
                )
            )
        return artifacts.read_svg()
