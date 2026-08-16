from __future__ import annotations

import re
import shutil
from pathlib import Path

_PAGE_SUFFIX_RE_CACHE: dict[str, re.Pattern[str]] = {}


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


# Compatibility aliases for older tests/imports that reached into executor internals.
_find_svg_output_path = find_svg_output_path
_canonicalize_svg_output_path = canonicalize_svg_output_path