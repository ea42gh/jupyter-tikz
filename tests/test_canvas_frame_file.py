from __future__ import annotations

from pathlib import Path

from jupyter_tikz.canvas_frame import apply_canvas_frame_to_svg_file

_SVG_MIN = (
    '<svg width="10" height="10" viewBox="0 0 10 10" '
    'xmlns="http://www.w3.org/2000/svg"></svg>'
)


def test_apply_canvas_frame_to_svg_file_accepts_bool(tmp_path: Path) -> None:
    p = tmp_path / "a.svg"
    p.write_text(_SVG_MIN)

    apply_canvas_frame_to_svg_file(p, True)

    out = p.read_text()
    assert 'id="jupyter_tikz_canvas_frame"' in out
    assert "<rect" in out
    assert out.strip().endswith("</svg>")


def test_apply_canvas_frame_to_svg_file_accepts_mapping(tmp_path: Path) -> None:
    p = tmp_path / "b.svg"
    p.write_text(_SVG_MIN)

    apply_canvas_frame_to_svg_file(
        p, {"stroke": "red", "stroke_width": 2.0, "inset": 1.0}
    )

    out = p.read_text()
    assert 'id="jupyter_tikz_canvas_frame"' in out
    # inset=1.0 on a 10x10 viewBox yields an 8x8 frame.
    assert 'x="1.0"' in out
    assert 'y="1.0"' in out
    assert 'width="8.0"' in out
    assert 'height="8.0"' in out
    assert 'stroke="red"' in out
    assert 'stroke-width="2.0"' in out
