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


def _tail_file(path: Path, *, limit_chars: int = 8000) -> str:
    """Read a file tail safely for inclusion in exceptions."""
    try:
        if not path.exists():
            return f"<missing: {path.name}>"
        txt = path.read_text(errors="replace")
    except Exception:
        return f"<unreadable: {path.name}>"
    if len(txt) <= limit_chars:
        return txt
    return txt[-limit_chars:]

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
    """Return the sequence of command invocations needed for this toolchain.

    This function is pure: it does not execute anything. Tests rely on the exact
    "shape" of the converter command for each toolchain.

    - PDF-based converters (pdftocairo/pdf2svg) take:  <job>.pdf <job>.svg
    - dvisvgm takes:  --output=<job>.svg --page=1 <job>.dvi
    """
    cmds: List[List[str]] = []

    # LaTeX step (run in workdir; input is by filename).
    cmds.append(list(toolchain.latex_cmd) + [tex_file.name])

    svg_cmd = list(toolchain.svg_cmd)
    is_dvisvgm = bool(svg_cmd) and svg_cmd[0] == "dvisvgm"

    if is_dvisvgm:
        # dvisvgm implements crop modes via flags.
        if crop_mode == "tight":
            svg_cmd += ["--bbox=min"]
            if exact_bbox:
                svg_cmd += ["--exact-bbox"]
        elif crop_mode == "page":
            svg_cmd += ["--bbox=papersize"]
        elif crop_mode == "none":
            pass

        # Deterministic output naming and page selection.
        svg_cmd += [f"--output={output_stem}.svg", "--page=1", f"{output_stem}.dvi"]
        cmds.append(svg_cmd)
        return cmds

    # PDF-based converters.
    if toolchain.needs_pdf:
        cmds.append(svg_cmd + [f"{output_stem}.pdf", f"{output_stem}.svg"])
        return cmds

    # Other DVI converters (not currently used).
    if toolchain.needs_dvi:
        cmds.append(svg_cmd + [f"{output_stem}.dvi", f"{output_stem}.svg"])
        return cmds

    raise ValueError(f"Invalid toolchain wiring: {toolchain.name!r}")
# -------------------------------------------------------------------------------------------------------------------


_PAGE_SUFFIX_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _find_svg_output_path(workdir: Path, output_stem: str) -> Path | None:
    """
    Return the SVG file produced by the converter for output_stem, or None.

    Most converters write exactly ``{output_stem}.svg``. However, some (notably
    pdftocairo and dvisvgm) may emit numbered page suffixes like
    ``{output_stem}-1.svg`` for single-page documents (and ``-2``, ``-3``, ...
    for multi-page documents). We select deterministically:

      1) Prefer the exact ``{output_stem}.svg`` if present
      2) Otherwise, prefer the lowest numeric page suffix ``{output_stem}-N.svg``
      3) Otherwise, fall back to the lexicographically-first ``{output_stem}-*.svg``

    Note: if multiple numbered outputs exist, callers receive the *first* page.
    All other pages remain in workdir as artifacts.
    """
    exact = workdir / f"{output_stem}.svg"
    if exact.exists():
        return exact

    matches = list(workdir.glob(f"{output_stem}-*.svg"))
    if not matches:
        return None

    # Cache the per-stem regex to avoid recompilation inside tight loops.
    rx = _PAGE_SUFFIX_RE_CACHE.get(output_stem)
    if rx is None:
        rx = re.compile(rf"^{re.escape(output_stem)}-(\d+)\.svg$")
        _PAGE_SUFFIX_RE_CACHE[output_stem] = rx

    numbered: list[tuple[int, Path]] = []
    unnumbered: list[Path] = []
    for p in matches:
        m = rx.match(p.name)
        if m:
            numbered.append((int(m.group(1)), p))
        else:
            unnumbered.append(p)

    if numbered:
        numbered.sort(key=lambda t: t[0])
        return numbered[0][1]

    return sorted(unnumbered or matches, key=lambda p: p.name)[0]
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
    strip_xml_declaration: bool = True,
) -> RenderArtifacts:
    """Compile TeX and keep artifacts in ``output_dir``.

    On failure, raises :class:`RenderError` with stderr/log tails and paths.
    """
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")

    tc = TOOLCHAINS[resolved_toolchain]
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    artifacts = _run_toolchain_in_dir(
        tc,
        tex_source,
        outdir,
        output_stem,
        crop_mode=crop_mode,
        enforce_tight_crop=enforce_tight_crop,
        exact_bbox=exact_bbox,
        padding=pad,
    )

    if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
        stderr_tail = artifacts.read_stderr_tail()
        log_tail = artifacts.read_latex_log_tail(output_stem=output_stem)
        raise RenderError(
            "Toolchain execution failed.\n"
            f"Artifacts kept at: {outdir}.\n"
            f"See stderr at: {artifacts.stderr_path}\n"
            f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
            "---- stderr tail ----\n"
            f"{stderr_tail}\n"
            "---- latex log tail ----\n"
            f"{log_tail}"
        )

    if artifacts.svg_path is None:
        raise RenderError(
            "SVG output not produced.\n"
            f"Artifacts kept at: {outdir}.\n"
            f"See stderr at: {artifacts.stderr_path}"
        )

    if frame and artifacts.svg_path is not None:
        apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

    if strip_xml_declaration and artifacts.svg_path is not None:
        raw = artifacts.svg_path.read_text(errors="replace")
        norm = strip_svg_xml_declaration(raw)
        if norm != raw:
            artifacts.svg_path.write_text(norm)

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
    strip_xml_declaration: bool = True,
) -> ExecutionResult:
    """Run a toolchain in a temporary directory and return captured outputs."""
    returncodes: list[int] = []
    stdout: list[str] = []
    stderr: list[str] = []
    svg_text: str | None = None

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

        svg_path = _find_svg_output_path(workdir, output_stem)
        if svg_path is not None and svg_path.exists():
            if enforce_tight_crop and crop_mode == "tight" and (not toolchain.svg_cmd or toolchain.svg_cmd[0] != "dvisvgm"):
                crop_svg_inplace(svg_path)
            if not pad.is_zero():
                apply_padding_to_svg_file(svg_path, pad)
            svg_text = svg_path.read_text(errors="replace")
            if strip_xml_declaration and svg_text is not None:
                svg_text = strip_svg_xml_declaration(svg_text)
            if frame and svg_text is not None:
                svg_text = apply_canvas_frame_to_svg_text(svg_text, frame)

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
        svg = self.svg_path.read_text(errors="replace")
        return strip_svg_xml_declaration(svg) if strip_xml_declaration else svg

    def read_stderr_tail(self, *, limit_chars: int = 4000) -> str:
        return _tail_file(self.stderr_path, limit_chars=limit_chars)

    def read_latex_log_tail(self, *, output_stem: str = "output", limit_chars: int = 8000) -> str:
        return _tail_file(self.workdir / f"{output_stem}.log", limit_chars=limit_chars)

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
    """Compile TeX and return SVG text.

    Artifacts retention
    -------------------
    - ``artifacts_path=<prefix>`` writes ``<prefix>.tex/.svg/.stdout.txt/.stderr.txt``.
    - ``artifacts_path=<dir>`` (existing directory) writes ``{output_stem}-{md5(tex)[:8]}.*``.
    - ``artifacts_path=True`` keeps a dedicated temp directory.
    - On failure, artifacts are always preserved and the exception includes the path.
    """
    resolved_toolchain = resolve_toolchain_name(toolchain_name)
    if resolved_toolchain not in TOOLCHAINS:
        raise ValueError(f"Unknown toolchain: {resolved_toolchain}")

    tc = TOOLCHAINS[resolved_toolchain]
    crop_mode, enforce_tight_crop = resolve_crop_policy(crop, tc)
    pad = normalize_padding(padding)

    def _maybe_strip(svg_text: str) -> str:
        return strip_svg_xml_declaration(svg_text) if strip_xml_declaration else svg_text

    def _copy_keep(src_dir: Path) -> Path:
        kept = Path(tempfile.mkdtemp(prefix="jupyter_tikz_failure_"))
        shutil.copytree(src_dir, kept, dirs_exist_ok=True)
        return kept

    # If the caller is not persisting artifacts, we can use the cache paths.
    if artifacts_path is None and cache and pad.is_zero():
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

    if artifacts_path is None and cache and (not pad.is_zero()):
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

    # Resolve a kept workdir/stem if requested.
    kept_workdir: Path | None = None
    kept_stem = output_stem

    if artifacts_path is not None and artifacts_path is not False:
        if artifacts_path is True:
            kept_workdir = Path(tempfile.mkdtemp(prefix="jupyter_tikz_artifacts_"))
        else:
            p = Path(artifacts_path)
            if p.exists() and p.is_dir():
                h8 = md5(tex_source.encode("utf-8")).hexdigest()[:8]
                kept_workdir = p
                kept_stem = f"{output_stem}-{h8}"
            else:
                kept_workdir = p.parent
                kept_workdir.mkdir(parents=True, exist_ok=True)
                kept_stem = p.name

    def _run_in(workdir: Path, stem: str) -> RenderArtifacts:
        return _run_toolchain_in_dir(
            tc,
            tex_source,
            workdir,
            stem,
            crop_mode=crop_mode,
            enforce_tight_crop=enforce_tight_crop,
            exact_bbox=exact_bbox,
            padding=pad,
        )

    # Kept run path (caller requested artifacts).
    if kept_workdir is not None:
        artifacts = _run_in(kept_workdir, kept_stem)
        if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
            raise RenderError(
                "Toolchain execution failed.\n"
                f"Artifacts kept at: {kept_workdir}.\n"
                f"See stderr at: {artifacts.stderr_path}\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{artifacts.read_stderr_tail()}\n"
                "---- latex log tail ----\n"
                f"{artifacts.read_latex_log_tail(output_stem=kept_stem)}"
            )
        if artifacts.svg_path is None:
            raise RenderError(
                "SVG output not produced.\n"
                f"Artifacts kept at: {kept_workdir}.\n"
                f"See stderr at: {artifacts.stderr_path}"
            )

        if frame and artifacts.svg_path is not None:
            apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

        svg = artifacts.read_svg(strip_xml_declaration=False)
        return _maybe_strip(svg)

    # Ephemeral run: preserve artifacts on failure.
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        artifacts = _run_in(tmpdir, output_stem)

        if not artifacts.returncodes or artifacts.returncodes[-1] != 0:
            kept = _copy_keep(tmpdir)
            raise RenderError(
                "Toolchain execution failed.\n"
                f"Artifacts kept at: {kept}.\n"
                f"See stderr at: {kept / f'{output_stem}.stderr.txt'}\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{_tail_file(kept / f'{output_stem}.stderr.txt', limit_chars=4000)}\n"
                "---- latex log tail ----\n"
                f"{_tail_file(kept / f'{output_stem}.log', limit_chars=8000)}"
            )

        if artifacts.svg_path is None:
            kept = _copy_keep(tmpdir)
            raise RenderError(
                "SVG output not produced.\n"
                f"Artifacts kept at: {kept}.\n"
                f"See stderr at: {kept / f'{output_stem}.stderr.txt'}"
            )

        if frame and artifacts.svg_path is not None:
            apply_canvas_frame_to_svg_file(artifacts.svg_path, frame)

        svg = artifacts.read_svg(strip_xml_declaration=False)
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
            # Re-use the same error formatting logic as render_svg by raising.
            stderr_tail = artifacts.stderr_path.read_text(errors="replace")[-4000:]
            raise RenderError(
                "Toolchain execution failed.\n"
                f"Last returncode: {artifacts.returncodes[-1] if artifacts.returncodes else 'n/a'}.\n"
                "---- stderr tail ----\n"
                f"{stderr_tail}"
            )
        return artifacts.read_svg()
