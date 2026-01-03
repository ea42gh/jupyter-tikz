from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Tuple


_UNIT_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s*([a-zA-Z]+))?\s*$")


def _to_svg_user_units(value: Any) -> float:
    """Convert a numeric value or a CSS-like length string to SVG user units.

    The conversion uses the common SVG/CSS convention of 96 dpi:
      - 1in = 96
      - 1pt = 96/72
      - 1cm = 96/2.54
      - 1mm = 96/25.4
      - 1px = 1

    If `value` is a number, it is treated as SVG user units.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise TypeError(f"Unsupported padding value type: {type(value)}")

    m = _UNIT_RE.match(value)
    if not m:
        raise ValueError(f"Invalid length: {value!r}")
    mag = float(m.group(1))
    unit = (m.group(2) or "").lower()

    if unit in ("", "px"):
        return mag
    if unit == "pt":
        return mag * (96.0 / 72.0)
    if unit == "in":
        return mag * 96.0
    if unit == "cm":
        return mag * (96.0 / 2.54)
    if unit == "mm":
        return mag * (96.0 / 25.4)

    raise ValueError(f"Unsupported unit: {unit!r}")


def normalize_padding(padding: Any) -> Tuple[float, float, float, float]:
    """Normalize user padding into (left, right, top, bottom) in SVG user units.

    Accepted forms:
      - None -> (0,0,0,0)
      - number or length string -> uniform padding on all sides
      - (x, y) -> left/right=x, top/bottom=y
      - (l, r, t, b) -> explicit per-side
      - {"left":..., "right":..., "top":..., "bottom":...}
        plus optional {"x":..., "y":...} to set both axes.
    """
    if padding is None:
        return (0.0, 0.0, 0.0, 0.0)

    # Uniform
    if isinstance(padding, (int, float, str)):
        u = _to_svg_user_units(padding)
        _validate_non_negative(u, "padding")
        return (u, u, u, u)

    # Tuples/lists
    if isinstance(padding, (tuple, list)):
        if len(padding) == 2:
            x = _to_svg_user_units(padding[0])
            y = _to_svg_user_units(padding[1])
            _validate_non_negative(x, "padding[0]")
            _validate_non_negative(y, "padding[1]")
            return (x, x, y, y)
        if len(padding) == 4:
            l = _to_svg_user_units(padding[0])
            r = _to_svg_user_units(padding[1])
            t = _to_svg_user_units(padding[2])
            b = _to_svg_user_units(padding[3])
            _validate_non_negative(l, "padding[0]")
            _validate_non_negative(r, "padding[1]")
            _validate_non_negative(t, "padding[2]")
            _validate_non_negative(b, "padding[3]")
            return (l, r, t, b)
        raise ValueError("padding tuple/list must be length 2 or 4")

    # Dict
    if isinstance(padding, Mapping):
        x = padding.get("x", None)
        y = padding.get("y", None)

        left = padding.get("left", x)
        right = padding.get("right", x)
        top = padding.get("top", y)
        bottom = padding.get("bottom", y)

        l = _to_svg_user_units(left)
        r = _to_svg_user_units(right)
        t = _to_svg_user_units(top)
        b = _to_svg_user_units(bottom)

        _validate_non_negative(l, "padding.left")
        _validate_non_negative(r, "padding.right")
        _validate_non_negative(t, "padding.top")
        _validate_non_negative(b, "padding.bottom")

        return (l, r, t, b)

    raise TypeError(f"Unsupported padding type: {type(padding)}")


def _validate_non_negative(v: float, name: str) -> None:
    if v < 0:
        raise ValueError(f"{name} must be non-negative")


def is_inkscape_available() -> bool:
    return shutil.which("inkscape") is not None


def inkscape_tight_crop_svg_inplace(svg_path: Path) -> bool:
    """Tight-crop an SVG to its drawing area using Inkscape.

    Returns True if cropping was performed successfully, False otherwise.
    """
    if not is_inkscape_available():
        return False

    # Inkscape ≥1.0 CLI
    cmd = [
        "inkscape",
        str(svg_path),
        "--export-area-drawing",
        "--export-filename",
        str(svg_path),
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode == 0


# Back-compat alias used elsewhere in the codebase.
def crop_svg_inplace(svg_path: Path) -> bool:
    return inkscape_tight_crop_svg_inplace(svg_path)


_VIEWBOX_RE = re.compile(r'\bviewBox\s*=\s*"([^"]+)"')
_WIDTH_RE = re.compile(r'\bwidth\s*=\s*"([^"]+)"')
_HEIGHT_RE = re.compile(r'\bheight\s*=\s*"([^"]+)"')
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)


def apply_viewbox_padding(svg_text: str, padding: Any) -> str:
    """Expand (or create) an SVG viewBox by per-side padding.

    Padding is applied by modifying viewBox only:
      minX -= left
      minY -= top
      width += left + right
      height += top + bottom

    If the SVG has no viewBox, one will be synthesized from width/height if
    possible.
    """
    l, r, t, b = normalize_padding(padding)
    if (l, r, t, b) == (0.0, 0.0, 0.0, 0.0):
        return svg_text

    # Parse viewBox if present
    m = _VIEWBOX_RE.search(svg_text)
    if m:
        vb = m.group(1).replace(",", " ").split()
        if len(vb) != 4:
            # Unrecognized viewBox; no-op rather than corrupting.
            return svg_text
        try:
            minx, miny, w, h = (float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3]))
        except Exception:
            return svg_text

        minx -= l
        miny -= t
        w += l + r
        h += t + b

        new_vb = _format_viewbox(minx, miny, w, h)
        return _VIEWBOX_RE.sub(f'viewBox="{new_vb}"', svg_text, count=1)

    # No viewBox: try to synthesize from width/height.
    w_m = _WIDTH_RE.search(svg_text)
    h_m = _HEIGHT_RE.search(svg_text)
    if not w_m or not h_m:
        return svg_text

    try:
        w = _to_svg_user_units(w_m.group(1))
        h = _to_svg_user_units(h_m.group(1))
    except Exception:
        return svg_text
    if w <= 0 or h <= 0:
        return svg_text

    minx, miny = 0.0 - l, 0.0 - t
    w2, h2 = w + l + r, h + t + b
    new_vb = _format_viewbox(minx, miny, w2, h2)

    open_m = _SVG_OPEN_RE.search(svg_text)
    if not open_m:
        return svg_text

    tag = open_m.group(0)
    if tag.endswith(">"):  # normal
        new_tag = tag[:-1] + f' viewBox="{new_vb}">'
    else:
        return svg_text

    return svg_text[: open_m.start()] + new_tag + svg_text[open_m.end() :]


def _format_viewbox(minx: float, miny: float, w: float, h: float) -> str:
    # Use a compact, stable float representation.
    return " ".join(f"{v:.6g}" for v in (minx, miny, w, h))


def apply_viewbox_padding_inplace(svg_path: Path, padding: Any) -> bool:
    """Apply viewBox padding to an SVG file in place.

    Returns True if a modification occurred.
    """
    original = svg_path.read_text(errors="replace")
    updated = apply_viewbox_padding(original, padding)
    if updated == original:
        return False
    svg_path.write_text(updated)
    return True
