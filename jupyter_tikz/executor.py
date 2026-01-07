from __future__ import annotations

import os
import re
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
from jupyter_tikz.canvas_frame import apply_canvas_frame_to_svg_file, apply_canvas_frame_to_svg_text
from jupyter_tikz.toolchains import Toolchain, TOOLCHAINS

#from typing import Sequence

# =======================================================================================================
_XML_DECL_RE = re.compile(r"^\ufeff?\s*<\?xml[^>]*\?>\s*", re.IGNORECASE | re.DOTALL)
_DOCTYPE_RE = re.compile(r"^\s*<!DOCTYPE[^>]*>\s*", re.IGNORECASE | re.DOTALL)


def strip_svg_xml_declaration(svg_text: str) -> str:
    """Strip optional XML prolog / doctype from an SVG string.

    Many SVG converters emit an XML declaration, e.g.::

        <?xml version="1.0" encoding="UTF-8" standalone="no"?>

    That prolog is legal XML but can break consumers that expect an inline
    ``<svg ...>`` root (e.g. Panel's ``pn.pane.SVG``). Removing it is safe for
    typical inline usage and does not alter the SVG element tree.

    This function is intentionally conservative: it only strips leading prolog
    constructs and leaves the rest of the document untouched.
    """

    if not svg_text:
        return svg_text

    out = _XML_DECL_RE.sub("", svg_text, count=1)
    # Some converters also emit a doctype line; strip it if present.
    out = _DOCTYPE_RE.sub("", out, count=1)
    return out.lstrip("\n")

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
        # pdf2svg's page argument is optional. We intentionally do not pass it,
        # so the converter command remains the simple, conventional 2-arg form:
        #   pdf2svg <input.pdf> <output.svg>
        # This also keeps the command shape consistent with other PDF-based
        # converters and with tests that validate command wiring.
        cmds.append(svg_cmd + [pdf, svg])
    elif toolchain.needs_dvi:
        dvi = f"{output_stem}.dvi"
        svg = f"{output_stem}.svg"
        # dvisvgm supports explicit output naming via --output. Using it avoids
        # relying on dvisvgm's default naming conventions (e.g. appending page
        # numbers when a DVI contains more than one page).
        if svg_cmd and svg_cmd[0] == "dvisvgm":
            cmds.append(svg_cmd + ["--page=1", f"--output={svg}", dvi])
        else:
            cmds.append(svg_cmd + [dvi, svg])

    return cmds


def _find_svg_output_path(workdir: Path, output_stem: str) -> Path | None:
    """Locate the SVG output produced by the conversion step.

    Most converters produce exactly ``{output_stem}.svg``. Some tool versions
    may emit numbered outputs (e.g. ``{output_stem}-1.svg``) when they treat
    the input as multi-page.

    This helper is a fallback used only when the canonical output name isn't
    present.
    """

    canonical = workdir / f"{output_stem}.svg"
    if canonical.exists():
        return canonical

    # Common fallback patterns.
    candidates = sorted(workdir.glob(f"{output_stem}-*.svg"))
    if candidates:
        return candidates[0]

    return None
# -------------------------------------------------------------------------------------------------------------------


def _persist_failure_artifacts(workdir: Path) -> Path:
    """Copy a temporary workdir to a persistent location for debugging.

    This is used on failures when the caller did not request kept artifacts.
    """
    dest = Path(tempfile.mkdtemp(prefix="jupyter_tikz_fail_"))
    try:
        shutil.copytree(workdir, dest, dirs_exist_ok=True)
    except Exception:
        # Best-effort fallback; do not mask the original error.
        try:
            for p in workdir.rglob("*"):
                rel = p.relative_to(workdir)
                target = dest / rel
                if p.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, target)
        except Exception:
            pass
    return dest

def _resolve_artifacts_target(
    artifacts_path: str | Path | bool,
    *,
    output_stem: str,
    tex_source: str,
) -> tuple[Path, str]:
    """Resolve an artifacts_path value into (workdir, output_stem).

    Semantics
    ---------
    * artifacts_path=True:
        Keep artifacts in a newly-created temp directory; return that directory.
    * artifacts_path=<existing directory>:
        Keep artifacts *in that directory*, using a unique stem derived from the
        TeX hash to avoid collisions.
    * artifacts_path=<path-like prefix> (file-like):
        Treat the value as a path prefix. The parent directory is created and
        artifacts are written as:

            <parent>/<name>.tex/.pdf/.svg/.log/.stdout.txt/.stderr.txt/...

      This supports both directory targets and file-prefix targets.
    """
    if artifacts_path is True:
        return (Path(tempfile.mkdtemp(prefix="jupyter_tikz_keep_")), output_stem)

    p = Path(str(artifacts_path)).expanduser()

    # If the user passed a filename with an extension, drop it so the stem
    # controls all artifact names consistently.
    if p.suffix:
        p = p.with_suffix("")

    if p.exists() and p.is_dir():
        h8 = md5(tex_source.encode("utf-8")).hexdigest()[:8]
        stem = f"{output_stem}-{h8}" if output_stem else h8
        return (p, stem)

    parent = p.parent
    if str(parent) in ("", "."):
        parent = Path.cwd()
    parent.mkdir(parents=True, exist_ok=True)
    return (parent, p.name)


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

    svg_path = _find_svg_output_path(workdir, output_stem)
    if svg_path is not None and svg_path.exists():
        # Normalize numbered outputs (e.g. output-1.svg) to output.svg for
        # consistent artifact paths.
        canonical = workdir / f"{output_stem}.svg"
        if svg_path != canonical:
            try:
                svg_path.replace(canonical)
                svg_path = canonical
            except Exception:
                # If renaming fails, proceed with the discovered path.
                pass
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
    frame=None,
    exact_bbox: bool = False,
) -> RenderArtifacts:
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
        # include last stderr chunk to make failures actionable
        raise RenderError(
            "Toolchain execution failed. See stderr at: "
            f"{artifacts.stderr_path}"
        )

    if artifacts.svg_path is None:
        raise RenderError("SVG output not produced")

    if frame and artifacts.svg_path is not None:
        apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

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
    frame=None,
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
                cwd=str(workdir),              # ← str() is correct
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            returncodes.append(proc.returncode)
            stdout.append(proc.stdout)
            stderr.append(proc.stderr)

            if proc.returncode != 0:
                break

        svg_path = _find_svg_output_path(workdir, output_stem)
        if svg_path is not None and svg_path.exists():
            canonical = workdir / f"{output_stem}.svg"
            if svg_path != canonical:
                try:
                    svg_path.replace(canonical)
                    svg_path = canonical
                except Exception:
                    pass
            if enforce_tight_crop and crop_mode == "tight" and (not toolchain.svg_cmd or toolchain.svg_cmd[0] != "dvisvgm"):
                crop_svg_inplace(svg_path)
            if not pad.is_zero():
                apply_padding_to_svg_file(svg_path, pad)
            svg_text = svg_path.read_text(errors="replace")
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

    def read_svg(self) -> str:
        if self.svg_path is None or not self.svg_path.exists():
            raise RenderError("SVG output not produced")
        return self.svg_path.read_text()
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
    cache: bool = True,
    strip_xml_declaration: bool = True,
    artifacts_path: str | Path | bool | None = None,
) -> str:
    """
    Compile TeX and return SVG text.

    Diagnostics
    -----------
    If compilation/conversion fails, the raised :class:`RenderError` will include a
    short tail of stderr and the LaTeX .log tail.

    For deeper debugging, set ``JUPYTER_TIKZ_KEEP_TEMP=1`` to keep the temporary
    build directory; the exception message will include the path.

    To keep intermediate and output files for successful renders, pass
    ``artifacts_path=...``.
    """
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")

    tc = TOOLCHAINS[resolved_toolchain]
    keep_env = os.environ.get("JUPYTER_TIKZ_KEEP_TEMP") == "1"
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)
    jobname = output_stem

    def _maybe_strip(svg_text: str) -> str:
        return strip_svg_xml_declaration(svg_text) if strip_xml_declaration else svg_text

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
        # pdflatex produces <jobname>.log, where jobname is output_stem
        return _tail_file(workdir / f"{jobname}.log", limit_chars=limit_chars)

    if artifacts_path:
        workdir, jobname = _resolve_artifacts_target(
            artifacts_path,
            output_stem=output_stem,
            tex_source=tex_source,
        )
        artifacts = _run_toolchain_in_dir(
            tc,
            tex_source,
            workdir,
            jobname,
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
        svg = artifacts.read_svg()
        if frame and artifacts.svg_path is not None:
            apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)
            svg = artifacts.read_svg()
        return _maybe_strip(svg)

    if keep_env:
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
            svg = artifacts.read_svg()
            if frame and artifacts.svg_path is not None:
                apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)
                svg = artifacts.read_svg()
            return _maybe_strip(svg)
        except Exception:
            # Do not delete workdir when keep_env=1
            raise
    else:
        # In-memory cache only applies to the "no kept artifacts" path.
        if cache and pad.is_zero():
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
        if cache and (not pad.is_zero()):
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
                kept = _persist_failure_artifacts(workdir)
                stderr_tail = _stderr_tail(artifacts.stderr_path)
                log_tail = _latex_log_tail(workdir)
                raise RenderError(
                    "Toolchain execution failed. "
                    f"Artifacts kept at: {kept}.\n"
                    f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                    "---- stderr tail ----\n"
                    f"{stderr_tail}\n"
                    "---- latex log tail ----\n"
                    f"{log_tail}"
                )


            svg = artifacts.read_svg()
            if frame and artifacts.svg_path is not None:
                apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)
                svg = artifacts.read_svg()
            return _maybe_strip(svg)


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

    # Last resort: stable fallback.
    return next(iter(TOOLCHAINS.keys()))




def resolve_crop_policy(
    crop: Literal["tight", "page", "none"] | None,
    toolchain: Toolchain,
) -> tuple[Literal["tight", "page", "none"], bool]:
    """Resolve crop mode and whether to enforce tight-cropping.

    Semantics
    ---------
    - For *dvisvgm* toolchains, tight/page/none are implemented via dvisvgm flags;
      no Inkscape-based enforcement is needed (enforce=False).
    - For PDF->SVG toolchains (pdftocairo/pdf2svg), tight-cropping is enforced via
      Inkscape only when ``mode == "tight"`` and Inkscape is available.

    Defaults
    --------
    ``crop=None`` defaults to ``mode="tight"`` to preserve historical outputs.
    """
    if crop in ("tight", "page", "none"):
        mode = crop
    else:
        mode = "tight"

    is_dvisvgm = bool(toolchain.svg_cmd) and toolchain.svg_cmd[0] == "dvisvgm"
    if is_dvisvgm:
        return (mode, False)

    # PDF toolchains: only tight is enforced (via Inkscape).
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
            kept = _persist_failure_artifacts(workdir)

            stderr_tail = artifacts.stderr_path.read_text(errors="replace")[-4000:]

            log_path = workdir / f"{jobname}.log"
            try:
                if not log_path.exists():
                    log_tail = f"<missing: {log_path.name}>"
                else:
                    log_tail = log_path.read_text(errors="replace")[-8000:]
            except Exception:
                log_tail = f"<unreadable: {log_path.name}>"

            raise RenderError(
                "Toolchain execution failed. "
                f"Artifacts kept at: {kept}.\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{stderr_tail}\n"
                "---- latex log tail ----\n"
                f"{log_tail}"
            )
        return artifacts.read_svg()



