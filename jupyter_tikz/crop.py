from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union

# ======================================================================================
# Inkscape tight-crop (in-place)
# ======================================================================================

# def _debug_enabled() -> bool:
#    return os.environ.get("JUPYTER_TIKZ_DEBUG") == "1"


def _is_probably_recursive_wrapper(p: Path) -> bool:
    """
    Heuristic: broken wrappers call `inkscape` via PATH and recurse.
    """
    try:
        data = p.read_text(errors="ignore")
    except Exception:
        return False
    if not data.startswith("#!"):
        return False
    patterns = [
        r"\bexec\s+inkscape\b",
        r"\bcommand\s+inkscape\b",
        r"\binkscape\s+\"\$@\"",
        r"\binkscape\s+\$@",
    ]
    return any(re.search(pat, data) for pat in patterns)


def _run_ok(cmd: Sequence[str], *, timeout_s: float = 2.0) -> bool:
    try:
        proc = subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _inkscape_candidates() -> list[str]:
    """
    Return inkscape candidates in PATH order, deduped by realpath.
    """
    seen: set[str] = set()
    out: list[str] = []

    for d in os.get_exec_path():
        cand = Path(d) / "inkscape"
        if not cand.exists():
            continue
        if not os.access(str(cand), os.X_OK):
            continue
        real = os.path.realpath(str(cand))
        if real in seen:
            continue
        seen.add(real)
        out.append(str(cand))

    first = shutil.which("inkscape")
    if first:
        real = os.path.realpath(first)
        if real not in seen:
            out.insert(0, first)

    return out


_WORKING_INKSCAPE: Optional[str] = None
_WORKING_INKSCAPE_CHECKED: bool = False


def _find_working_inkscape() -> Optional[str]:
    global _WORKING_INKSCAPE, _WORKING_INKSCAPE_CHECKED
    if _WORKING_INKSCAPE_CHECKED:
        return _WORKING_INKSCAPE

    _WORKING_INKSCAPE_CHECKED = True
    candidates = _inkscape_candidates()

    # if _debug_enabled():
    #    print("[crop] inkscape candidates:", candidates)

    for path in candidates:
        p = Path(path)
        if _is_probably_recursive_wrapper(p):
            # if _debug_enabled():
            #    print(f"[crop] skipping probable recursive wrapper: {path}")
            continue

        if _run_ok([path, "--version"], timeout_s=2.0):
            _WORKING_INKSCAPE = path
            # if _debug_enabled():
            #    try:
            #        v = subprocess.check_output([path, "--version"], text=True).strip()
            #        print(f"[crop] selected inkscape: {path}")
            #        print(f"[crop] inkscape --version: {v}")
            #    except Exception:
            #        print(f"[crop] selected inkscape: {path} (version read failed)")
            return _WORKING_INKSCAPE

        # if _debug_enabled():
        #    print(f"[crop] candidate failed --version: {path}")

    _WORKING_INKSCAPE = None
    # if _debug_enabled():
    #    print("[crop] no working inkscape found")
    return None


def crop_svg_inplace(svg_path: Path) -> bool:
    """
    Tight-crop an SVG in-place using Inkscape. Returns True if modified.
    """
    svg_path = Path(svg_path)
    if not svg_path.exists():
        return False

    inkscape = _find_working_inkscape()
    if inkscape is None:
        # if _debug_enabled():
        #    print("[crop] inkscape not available/working; skipping crop")
        return False

    before = svg_path.read_bytes()

    cmds: list[list[str]] = [
        [
            inkscape,
            str(svg_path),
            "--export-area-drawing",
            "--export-type=svg",
            f"--export-filename={svg_path}",
            "--export-overwrite",
        ],
        [
            inkscape,
            "--batch-process",
            str(svg_path),
            "--export-area-drawing",
            "--export-type=svg",
            f"--export-filename={svg_path}",
            "--export-overwrite",
        ],
        # 0.9x style
        [
            inkscape,
            "-z",
            str(svg_path),
            "--export-area-drawing",
            f"--export-svg={svg_path}",
        ],
        [inkscape, str(svg_path), "--export-area-drawing", f"--export-svg={svg_path}"],
    ]

    last_stderr = ""
    for cmd in cmds:
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30.0,
            )
        except Exception as e:
            # if _debug_enabled():
            #    print("[crop] exec exception:", repr(e))
            #    print("[crop] cmd:", " ".join(cmd))
            continue

        # if _debug_enabled():
        #    print("[crop] cmd:", " ".join(cmd))
        #    print("[crop] rc:", proc.returncode)
        #    if proc.stderr:
        #        print("[crop] stderr tail:", proc.stderr[-800:])

        if proc.returncode != 0:
            last_stderr = proc.stderr or last_stderr
            continue

        after = svg_path.read_bytes()
        changed = after != before
        # if _debug_enabled():
        #    print("[crop] changed:", changed)
        if changed:
            return True

    # if _debug_enabled():
    #    print("[crop] failed to crop; last stderr tail:", (last_stderr or "")[-800:])
    return False


# ======================================================================================
# Padding utilities (tuple API expected by tests/test_padding_options.py)
# ======================================================================================

PaddingTuple = Tuple[float, float, float, float]  # (left, right, top, bottom)

_LEN_RE = re.compile(r"^\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([a-zA-Z]*)\s*$")


def _to_px(value: Any) -> float:
    """
    Convert numeric or simple length strings to px-like float.
    Supports: px, pt, pc, in, cm, mm (and empty unit).
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        m = _LEN_RE.match(value)
        if not m:
            raise ValueError(f"Invalid length string: {value!r}")
        num = float(m.group(1))
        unit = (m.group(2) or "").lower()

        if unit in ("", "px"):
            return num
        if unit == "pt":
            return num * (96.0 / 72.0)
        if unit == "pc":  # pica = 12pt
            return num * (96.0 / 6.0)
        if unit == "in":
            return num * 96.0
        if unit == "cm":
            return num * (96.0 / 2.54)
        if unit == "mm":
            return num * (96.0 / 25.4)

        raise ValueError(f"Unsupported unit: {unit!r}")

    raise TypeError(f"Unsupported padding value type: {type(value).__name__}")


def normalize_padding(padding: Any) -> PaddingTuple:
    """
    Normalize padding into (left, right, top, bottom) float tuple.

    Accepted forms (as required by tests):
      - number:          p -> (p, p, p, p)
      - (x, y):          -> (x, x, y, y)
      - (l, r, t, b):    -> (l, r, t, b)
      - dict: supports keys: x, y, left, right, top, bottom
      - length string like "1pt"
    """
    if padding is None:
        return (0.0, 0.0, 0.0, 0.0)

    # "1pt" style
    if isinstance(padding, str):
        p = _to_px(padding)
        return (p, p, p, p)

    # uniform number
    if isinstance(padding, (int, float)):
        p = float(padding)
        return (p, p, p, p)

    # tuple/list
    if isinstance(padding, (tuple, list)):
        if len(padding) == 2:
            x = _to_px(padding[0])
            y = _to_px(padding[1])
            return (x, x, y, y)
        if len(padding) == 4:
            l = _to_px(padding[0])
            r = _to_px(padding[1])
            t = _to_px(padding[2])
            b = _to_px(padding[3])
            return (l, r, t, b)
        raise ValueError("Padding tuple/list must have length 2 or 4.")

    # dict
    if isinstance(padding, dict):
        x = _to_px(padding.get("x", 0.0))
        y = _to_px(padding.get("y", 0.0))

        left = _to_px(padding.get("left", x))
        right = _to_px(padding.get("right", x))
        top = _to_px(padding.get("top", y))
        bottom = _to_px(padding.get("bottom", y))
        return (left, right, top, bottom)

    raise TypeError(f"Unsupported padding spec: {type(padding).__name__}")


_VIEWBOX_RE = re.compile(r'\bviewBox\s*=\s*"([^"]+)"')
_WIDTH_RE = re.compile(r'\bwidth\s*=\s*"([^"]+)"')
_HEIGHT_RE = re.compile(r'\bheight\s*=\s*"([^"]+)"')
_SVG_TAG_RE = re.compile(r"<svg\b([^>]*)>", re.IGNORECASE)


def _fmt_num(x: float) -> str:
    # integers should print without .0 to satisfy tests
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    # otherwise strip trailing zeros
    s = f"{x:.12g}"
    return s


def _parse_viewbox(vb: str) -> tuple[float, float, float, float]:
    parts = vb.strip().replace(",", " ").split()
    if len(parts) != 4:
        raise ValueError(f"Invalid viewBox: {vb!r}")
    return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))


def apply_viewbox_padding(svg_or_path: Union[str, Path], padding: Any) -> str:
    """
    Apply viewBox padding (expand viewBox) and return SVG text.
    If svg_or_path is a Path (or a string that points to an existing file), update in-place.
    """
    l, r, t, b = normalize_padding(padding)

    # Load SVG text (from file or directly)
    svg_path: Optional[Path] = None
    if isinstance(svg_or_path, Path):
        svg_path = svg_or_path
        svg_text = svg_path.read_text(errors="replace")
    elif isinstance(svg_or_path, str) and Path(svg_or_path).exists():
        svg_path = Path(svg_or_path)
        svg_text = svg_path.read_text(errors="replace")
    else:
        svg_text = str(svg_or_path)

    # Find existing viewBox or infer from width/height
    m = _VIEWBOX_RE.search(svg_text)
    if m:
        x0, y0, w, h = _parse_viewbox(m.group(1))
    else:
        mw = _WIDTH_RE.search(svg_text)
        mh = _HEIGHT_RE.search(svg_text)
        if not (mw and mh):
            raise ValueError("SVG has no viewBox and no width/height to infer one.")
        w = _to_px(mw.group(1))
        h = _to_px(mh.group(1))
        x0, y0 = 0.0, 0.0

    nx0 = x0 - l
    ny0 = y0 - t
    nw = w + l + r
    nh = h + t + b

    new_vb = f"{_fmt_num(nx0)} {_fmt_num(ny0)} {_fmt_num(nw)} {_fmt_num(nh)}"

    if m:
        out = _VIEWBOX_RE.sub(lambda _: f'viewBox="{new_vb}"', svg_text, count=1)
    else:
        # Inject viewBox into the <svg ...> tag
        mt = _SVG_TAG_RE.search(svg_text)
        if not mt:
            raise ValueError("SVG tag not found.")
        attrs = mt.group(1)
        injected = f'<svg{attrs} viewBox="{new_vb}">'
        out = svg_text[: mt.start()] + injected + svg_text[mt.end() :]

    if svg_path is not None:
        svg_path.write_text(out)
    return out
