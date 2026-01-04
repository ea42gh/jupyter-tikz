from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import re


# -------------------------------------------------------------------------------------------------
# Padding type + normalization
# -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Padding:
    """
    Padding in SVG user units (same coordinate system as viewBox).
    """
    left: float = 0.0
    right: float = 0.0
    top: float = 0.0
    bottom: float = 0.0

    def is_zero(self) -> bool:
        return self.left == 0.0 and self.right == 0.0 and self.top == 0.0 and self.bottom == 0.0

    # Back-compat: allow tuple-like usage and comparisons.
    def __iter__(self):
        yield self.left
        yield self.right
        yield self.top
        yield self.bottom

    def __len__(self) -> int:
        return 4

    def __getitem__(self, idx: int) -> float:
        return (self.left, self.right, self.top, self.bottom)[idx]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list)) and len(other) == 4:
            try:
                ol, or_, ot, ob = (float(other[0]), float(other[1]), float(other[2]), float(other[3]))
            except Exception:
                return False
            return (
                self.left == ol
                and self.right == or_
                and self.top == ot
                and self.bottom == ob
            )
        return super().__eq__(other)


_NUM_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*$")
_LEN_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)([a-zA-Z%]*)\s*$")


def _parse_length(s: str) -> Tuple[float, str]:
    """
    Parse an SVG length like '277.07422pt' or '10' into (value, unit).
    Unit may be '' (unitless) or a known absolute unit. '%' is treated as unsupported.
    """
    m = _LEN_RE.match(s)
    if not m:
        raise ValueError(f"Unparseable length: {s!r}")
    val = float(m.group(1))
    unit = m.group(2) or ""
    if unit == "%":
        raise ValueError("Relative % lengths are not supported for scaling.")
    return val, unit


def _fmt_length(val: float, unit: str) -> str:
    # Keep reasonably compact without scientific notation.
    s = format(float(val), ".15g")
    if "e" in s.lower():
        s = f"{float(val):.15f}".rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return f"{s}{unit}"


def _len_to_px(s: str) -> float:
    """
    Convert basic SVG/CSS lengths to px-equivalent.
    Used only when synthesizing a viewBox from width/height.
    """
    val, unit = _parse_length(s)
    u = unit.lower()

    if u in ("", "px"):
        return val
    if u == "pt":
        return val * (96.0 / 72.0)
    if u == "in":
        return val * 96.0
    if u == "cm":
        return val * (96.0 / 2.54)
    if u == "mm":
        return val * (96.0 / 25.4)

    raise ValueError(f"Unsupported unit in length: {s!r}")


def _fmt_num(x: float) -> str:
    """
    Format numbers for viewBox output.

    Tests expect integer-valued numbers to include '.0'
    (e.g. -2.0 0.0 12.0 10.0).
    """
    xf = float(x)
    s = format(xf, ".15g")

    if "e" in s.lower():
        s = f"{xf:.15f}".rstrip("0").rstrip(".")
        if s == "-0":
            s = "0"

    if "." not in s:
        s = s + ".0"

    if s.startswith("-0") and float(s) == 0.0:
        s = "0.0"

    return s


def normalize_padding(padding: Any) -> Padding:
    """
    Normalize user padding input to a Padding object.

    Supported:
      - None -> zero
      - number -> uniform
      - (x, y) -> left/right=x, top/bottom=y
      - (l, r, t, b) -> explicit
      - dict -> keys: x, y, left, right, top, bottom
               Missing sides default to 0; x/y apply only to their side-pairs.
      - string length like "12", "5px", "1pt" (treated as uniform)
    """
    if padding is None:
        return Padding()

    if isinstance(padding, Padding):
        return padding

    if isinstance(padding, (int, float)):
        v = float(padding)
        return Padding(v, v, v, v)

    if isinstance(padding, str):
        m = _NUM_RE.match(padding)
        if m:
            v = float(m.group(1))
            return Padding(v, v, v, v)
        v = _len_to_px(padding)
        return Padding(v, v, v, v)

    if isinstance(padding, (tuple, list)):
        seq = list(padding)
        if len(seq) == 2:
            x = float(seq[0])
            y = float(seq[1])
            return Padding(left=x, right=x, top=y, bottom=y)
        if len(seq) == 4:
            l, r, t, b = (float(seq[0]), float(seq[1]), float(seq[2]), float(seq[3]))
            return Padding(left=l, right=r, top=t, bottom=b)
        raise ValueError("Padding tuple/list must have length 2 or 4")

    if isinstance(padding, Mapping):
        d: Dict[str, Any] = dict(padding)

        x = float(d["x"]) if "x" in d else 0.0
        y = float(d["y"]) if "y" in d else 0.0

        left = float(d["left"]) if "left" in d else x
        right = float(d["right"]) if "right" in d else x
        top = float(d["top"]) if "top" in d else y
        bottom = float(d["bottom"]) if "bottom" in d else y

        return Padding(left=left, right=right, top=top, bottom=bottom)

    raise TypeError(f"Unsupported padding type: {type(padding).__name__}")


# -------------------------------------------------------------------------------------------------
# SVG viewBox padding (string-based, preserves namespaces and tag names)
# -------------------------------------------------------------------------------------------------

# Matches: viewBox="..." or viewBox='...'
_VIEWBOX_RE = re.compile(r'(\bviewBox\s*=\s*)(["\'])([^"\']*)(\2)', re.IGNORECASE)

# Matches: width="..." or width='...'
_WIDTH_RE = re.compile(r'(\bwidth\s*=\s*)(["\'])([^"\']*)(\2)', re.IGNORECASE)
_HEIGHT_RE = re.compile(r'(\bheight\s*=\s*)(["\'])([^"\']*)(\2)', re.IGNORECASE)

# First <svg ...> tag (non-greedy up to >)
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*?>", re.IGNORECASE | re.DOTALL)


def _parse_viewbox(vb: str) -> Tuple[float, float, float, float]:
    parts = vb.replace(",", " ").split()
    if len(parts) != 4:
        raise ValueError(f"Unexpected viewBox: {vb!r}")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def _scale_svg_dimension(svg_text: str, *, attr_re: re.Pattern, ratio: float) -> str:
    """
    Multiply width or height attribute by ratio, preserving units and quote style.
    If parsing fails or ratio is ~1, return original text.
    """
    if abs(ratio - 1.0) < 1e-12:
        return svg_text

    m = attr_re.search(svg_text)
    if not m:
        return svg_text

    prefix, q, raw, _q2 = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        val, unit = _parse_length(raw)
    except Exception:
        return svg_text

    new_raw = _fmt_length(val * ratio, unit)
    repl = f"{prefix}{q}{new_raw}{q}"
    return svg_text[: m.start()] + repl + svg_text[m.end() :]


def apply_padding_to_svg_text(svg_text: str, padding: Padding) -> str:
    """
    Apply padding by expanding viewBox and scaling viewport (width/height) proportionally.

    Why scale width/height?
      Expanding only viewBox changes the viewBox-to-viewport ratio. With the SVG default
      preserveAspectRatio ("xMidYMid meet"), that can shrink content uniformly and
      *appear* like padding on all sides. Scaling width/height by the same ratios keeps
      the content scale constant, so left-only padding looks like left-only margin.
    """
    if not isinstance(padding, Padding):
        padding = normalize_padding(padding)

    if padding.is_zero():
        return svg_text

    m = _VIEWBOX_RE.search(svg_text)

    if m:
        vb = m.group(3)
        try:
            x0, y0, w0, h0 = _parse_viewbox(vb)
        except Exception:
            return svg_text

        # Guard against degenerate boxes
        if w0 == 0.0 or h0 == 0.0:
            return svg_text

        x1 = x0 - padding.left
        y1 = y0 - padding.top
        w1 = w0 + padding.left + padding.right
        h1 = h0 + padding.top + padding.bottom

        # Update viewBox
        new_vb = f"{_fmt_num(x1)} {_fmt_num(y1)} {_fmt_num(w1)} {_fmt_num(h1)}"
        prefix = m.group(1)
        q = m.group(2)
        repl = f"{prefix}{q}{new_vb}{q}"
        out = svg_text[: m.start()] + repl + svg_text[m.end() :]

        # Scale viewport so content scale remains constant.
        rx = w1 / w0
        ry = h1 / h0
        out = _scale_svg_dimension(out, attr_re=_WIDTH_RE, ratio=rx)
        out = _scale_svg_dimension(out, attr_re=_HEIGHT_RE, ratio=ry)
        return out

    # No viewBox: synthesize from width/height and inject into <svg ...>, then scale width/height.
    mw = _WIDTH_RE.search(svg_text)
    mh = _HEIGHT_RE.search(svg_text)
    if not (mw and mh):
        return svg_text

    try:
        w_px = _len_to_px(mw.group(3))
        h_px = _len_to_px(mh.group(3))
    except Exception:
        return svg_text

    if w_px == 0.0 or h_px == 0.0:
        return svg_text

    x0, y0, w0, h0 = 0.0, 0.0, w_px, h_px
    x1 = x0 - padding.left
    y1 = y0 - padding.top
    w1 = w0 + padding.left + padding.right
    h1 = h0 + padding.top + padding.bottom

    new_vb = f"{_fmt_num(x1)} {_fmt_num(y1)} {_fmt_num(w1)} {_fmt_num(h1)}"

    msvg = _SVG_OPEN_RE.search(svg_text)
    if not msvg:
        return svg_text

    tag = msvg.group(0)
    insert_attr = f' viewBox="{new_vb}"'

    if tag.endswith("/>"):
        new_tag = tag[:-2] + insert_attr + "/>"
    elif tag.endswith(">"):
        new_tag = tag[:-1] + insert_attr + ">"
    else:
        return svg_text

    out = svg_text[: msvg.start()] + new_tag + svg_text[msvg.end() :]

    rx = w1 / w0
    ry = h1 / h0
    out = _scale_svg_dimension(out, attr_re=_WIDTH_RE, ratio=rx)
    out = _scale_svg_dimension(out, attr_re=_HEIGHT_RE, ratio=ry)
    return out


def apply_padding_to_svg_file(svg_path: Path, padding: Padding) -> None:
    if not isinstance(padding, Padding):
        padding = normalize_padding(padding)
    if padding.is_zero():
        return
    txt = svg_path.read_text(errors="replace")
    out = apply_padding_to_svg_text(txt, padding)
    svg_path.write_text(out)


# Backwards-compat alias (some tests/imports refer to this name)
apply_viewbox_padding = apply_padding_to_svg_text

