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


def test_normalize_svg_strips_namespace_declarations():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10"></svg>'
    out = normalize_svg(svg)
    assert "xmlns" not in out
    assert out == "<svg></svg>"


def test_normalize_svg_strips_inkscape_metadata():
    svg = '<svg width="10pt" height="10pt" viewBox="0 0 10 10" inkscape:version="1"><sodipodi:namedview pagecolor="#fff" /></svg>'
    out = normalize_svg(svg)
    assert "sodipodi" not in out
    assert "inkscape" not in out
    assert "viewBox" not in out
    assert "width=" not in out
    assert "height=" not in out
