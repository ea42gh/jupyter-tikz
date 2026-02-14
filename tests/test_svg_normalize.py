from jupyter_tikz.svg_normalize import normalize_svg


def test_normalize_svg_strips_internal_refs_and_ids():
    svg = """
    <svg viewBox="0 0 10 10">
      <defs>
        <clipPath id="clip0"><rect width="10" height="10"/></clipPath>
      </defs>
      <g clip-path="url(#clip0)"><rect width="10" height="10"/></g>
    </svg>
    """
    out = normalize_svg(svg)
    assert 'id="' not in out
    assert "url(#" not in out


def test_normalize_svg_removes_unreferenced_ids():
    svg = """
    <svg viewBox="0 0 10 10">
      <g id="surface1"><path d="M0 0h1v1H0z"/></g>
    </svg>
    """
    out = normalize_svg(svg)
    assert 'id="' not in out
