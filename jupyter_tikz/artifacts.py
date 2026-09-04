from __future__ import annotations

import os
import re
import shutil
import tempfile
from hashlib import md5
from pathlib import Path
from typing import Literal, Optional, Tuple, Union

from jupyter_tikz.diagnostics import format_toolchain_failure
from jupyter_tikz.naming import validate_output_stem
from jupyter_tikz.paths import validate_user_output_path
from jupyter_tikz.render_types import RenderArtifacts, RenderError
from jupyter_tikz.save_paths import resolve_save_destination

_PAGE_SUFFIX_RE_CACHE: dict[str, re.Pattern[str]] = {}


def raise_for_bad_artifacts(
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
def find_svg_output_path(workdir: Path, output_stem: str) -> Path | None:
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


def canonicalize_svg_output_path(
    workdir: Path, output_stem: str, found: Path | None
) -> Path | None:
    """Ensure the primary SVG artifact is available at ``{output_stem}.svg``.

    Some converters (notably pdftocairo) may emit numbered page suffix outputs
    like ``output-1.svg`` even when given a single-page PDF. Downstream code
    (and users) overwhelmingly expect to find the SVG at ``output.svg``.

    This helper preserves the original page-suffixed outputs as artifacts, but
    also materializes a canonical ``{output_stem}.svg`` alongside them.
    """

    if found is None:
        return None

    expected = workdir / f"{output_stem}.svg"
    if found == expected:
        return expected

    # If the converter already produced the expected output, prefer it.
    if expected.exists():
        return expected

    try:
        shutil.copy2(found, expected)
        return expected
    except Exception:
        # Fall back to the discovered path if we cannot copy.
        return found


def resolve_artifacts_target(
    tex_source: str,
    *,
    output_stem: str,
    artifacts_path: Optional[Union[str, os.PathLike]] = None,
    artifacts_prefix: Optional[Union[str, os.PathLike]] = None,
) -> Tuple[Path, str, bool]:
    """Resolve (workdir, stem, cleanup_on_success) for render_svg."""

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




def save_artifact(
    tex_obj,
    dest: str,
    ext: Literal["tikz", "tex", "png", "svg", "pdf"],
) -> None:
    """Save a legacy TexDocument artifact to its destination."""

    dest_path = resolve_save_destination(dest, ext)
    if ext == "tikz":
        if not tex_obj.tikz_code:
            raise ValueError("No TikZ code to save.")
        dest_path.write_text(tex_obj.tikz_code, encoding="utf-8")
    else:
        stem = str(getattr(tex_obj, "_active_output_stem", tex_obj._hex_hash))
        Path(stem).with_suffix(f".{ext}").replace(dest_path)
