from __future__ import annotations

import math

import sys
from pathlib import Path


# Allow running tests from a source checkout without installing the package.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


from jupyter_tikz.crop import apply_viewbox_padding, normalize_padding


def test_normalize_padding_uniform_number():
    assert normalize_padding(2) == (2.0, 2.0, 2.0, 2.0)


def test_normalize_padding_tuple_xy():
    assert normalize_padding((3, 4)) == (3.0, 3.0, 4.0, 4.0)


def test_normalize_padding_tuple_lrtb():
    assert normalize_padding((1, 2, 3, 4)) == (1.0, 2.0, 3.0, 4.0)


def test_normalize_padding_dict_mixed():
    # x applies to left/right unless overridden; y applies to top/bottom unless overridden.
    assert normalize_padding({"x": 5, "y": 6, "left": 1, "top": 2}) == (1.0, 5.0, 2.0, 6.0)


def test_normalize_padding_length_strings():
    # 1pt = 96/72 = 1.333333...
    l, r, t, b = normalize_padding("1pt")
    assert math.isclose(l, 96 / 72, rel_tol=1e-9)
    assert (l, r, t, b) == (l, l, l, l)


def test_apply_viewbox_padding_existing_viewbox():
    svg = '<svg viewBox="0 0 10 20"></svg>'
    out = apply_viewbox_padding(svg, {"left": 1, "right": 2, "top": 3, "bottom": 4})
    assert 'viewBox="-1 -3 13 27"' in out


def test_apply_viewbox_padding_inject_viewbox_from_width_height():
    svg = '<svg width="10" height="20"></svg>'
    out = apply_viewbox_padding(svg, 1)
    assert 'viewBox="-1 -1 12 22"' in out
