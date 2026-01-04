from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Tuple, Union

# Public spec type: render_svg(..., frame=...)
CanvasFrameSpec = Union[bool, Mapping[str, Any], None]


@dataclass(frozen=True)
class CanvasFrame:
    """Style options for a canvas frame drawn around the SVG canvas."""
    stroke: str = "#000000"
    stroke_width: float = 1.0
    fill: str = "none"
    opacity: float = 1.0
    inset: float = 0.0
    vector_effect: bool = True  # non-scaling stroke
    dasharray: str | None = None


# SVG parsing helpers (string-based to preserve namespaces/tag names exactly).
_VIEWBOX_RE = re.compile(r'(\bviewBox\s*=\s*)(["\'])([^"\']*)(\2)', re.IGNORECASE)
_WIDTH_RE = re.compile(r'(\bwidth\s*=\s*)(["\'])([^"\']*)(\2)', re.IGNORECASE)
_HEIGHT_RE = re.compile(r'(\bheight\s*=\s*)(["\'])([^"\']*)(\2)', re.IGNORECASE)
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*?>", re.IGNORECASE | re.DOTALL)
_SVG_CLOSE_RE = re.compile(r"</svg\s*>", re.IGNORECASE)

_LEN_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)([a-zA-Z%]*)\s*$")


def _parse_length(s: str) -> Tuple[float, str]:
    m = _LEN_RE.match(s)
    if not m:
        raise ValueError(f"Unparseable length: {s!r}")
    val = float(m.group(1))
    unit = m.group(2) or ""
    if unit == "%":
        raise ValueError("Relative % lengths are not supported.")
    return val, unit


def _len_to_px(s: str) -> float:
    """Convert absolute SVG/CSS lengths to px-equivalent."""
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
    Format numeric attributes.

    We keep this conservative: no scientific notation; preserve integer-ish values as '.0'
    to align with existing test expectations elsewhere.
    """
    xf = float(x)
    s = format(xf, ".15g")
    if "e" in s.lower():
        s = f"{xf:.15f}".rstrip("0").rstrip(".")
    if "." not in s:
        s = s + ".0"
    if s.startswith("-0") and float(s) == 0.0:
        s = "0.0"
    return s


def _parse_viewbox(vb: str) -> Tuple[float, float, float, float]:
    parts = vb.replace(",", " ").split()
    if len(parts) != 4:
        raise ValueError(f"Unexpected viewBox: {vb!r}")
    return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])


def normalize_canvas_frame(frame: CanvasFrameSpec) -> CanvasFrame | None:
    """Normalize `frame` input into a CanvasFrame object, or None if disabled."""
    if not frame:
        return None
    if frame is True:
        return CanvasFrame()
    if isinstance(frame, Mapping):
        d = dict(frame)
        return CanvasFrame(
            stroke=str(d.get("stroke", d.get("color", "#000000"))),
            stroke_width=float(d.get("stroke_width", d.get("width", 1.0))),
            fill=str(d.get("fill", "none")),
            opacity=float(d.get("opacity", 1.0)),
            inset=float(d.get("inset", 0.0)),
            vector_effect=bool(d.get("vector_effect", True)),
            dasharray=(None if d.get("dasharray") is None else str(d.get("dasharray"))),
        )
    raise TypeError("frame must be None, a bool, or a mapping of style options")


def _frame_rect_svg(x: float, y: float, w: float, h: float, frame: CanvasFrame) -> str:
    attrs = {
        "x": _fmt_num(x),
        "y": _fmt_num(y),
        "width": _fmt_num(w),
        "height": _fmt_num(h),
        "fill": frame.fill,
        "stroke": frame.stroke,
        "stroke-width": _fmt_num(frame.stroke_width),
        "opacity": _fmt_num(frame.opacity),
        "pointer-events": "none",
    }
    if frame.vector_effect:
        attrs["vector-effect"] = "non-scaling-stroke"
    if frame.dasharray:
        attrs["stroke-dasharray"] = frame.dasharray

    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f'<g id="jupyter_tikz_canvas_frame"><rect {attr_str} /></g>'


def apply_canvas_frame_to_svg_text(svg_text: str, frame: CanvasFrameSpec) -> str:
    """
    Inject a <rect> framing the SVG canvas.

    The frame is drawn in the SVG's coordinate system:
      - Prefer viewBox if present.
      - Else fall back to width/height (converted to px).
    """
    f = normalize_canvas_frame(frame)
    if f is None:
        return svg_text

    # Determine canvas bounds
    m_vb = _VIEWBOX_RE.search(svg_text)
    if m_vb:
        try:
            x0, y0, w0, h0 = _parse_viewbox(m_vb.group(3))
        except Exception:
            return svg_text
    else:
        mw = _WIDTH_RE.search(svg_text)
        mh = _HEIGHT_RE.search(svg_text)
        if not (mw and mh):
            return svg_text
        try:
            w0 = _len_to_px(mw.group(3))
            h0 = _len_to_px(mh.group(3))
        except Exception:
            return svg_text
        x0, y0 = 0.0, 0.0

    if w0 <= 0 or h0 <= 0:
        return svg_text

    inset = float(f.inset)
    x = x0 + inset
    y = y0 + inset
    w = max(0.0, w0 - 2.0 * inset)
    h = max(0.0, h0 - 2.0 * inset)

    rect = _frame_rect_svg(x, y, w, h, f)

    # Insert as last child before </svg> so it draws on top.
    m_close = None
    for m in _SVG_CLOSE_RE.finditer(svg_text):
        m_close = m
    if m_close:
        return svg_text[: m_close.start()] + rect + svg_text[m_close.start() :]

    # Handle self-closing <svg .../>
    m_open = _SVG_OPEN_RE.search(svg_text)
    if not m_open:
        return svg_text

    tag = m_open.group(0)
    if tag.endswith("/>"):
        new_open = tag[:-2] + ">"
        return svg_text[: m_open.start()] + new_open + rect + "</svg>" + svg_text[m_open.end() :]

    return svg_text


def apply_canvas_frame_to_svg_file(svg_path: Path, frame: CanvasFrameSpec) -> None:
    f = normalize_canvas_frame(frame)
    if f is None:
        return
    txt = svg_path.read_text(errors="replace")
    out = apply_canvas_frame_to_svg_text(txt, f)
    svg_path.write_text(out)
