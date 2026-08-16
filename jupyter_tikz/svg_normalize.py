import re

_XML_DECL_RE = re.compile(r"^\ufeff?\s*<\?xml[^>]*\?>\s*", re.IGNORECASE | re.DOTALL)
_DOCTYPE_RE = re.compile(r"^\s*<!DOCTYPE[^>]*>\s*", re.IGNORECASE | re.DOTALL)
_XMLNS_RE = re.compile(r"\sxmlns(?::\w+)?=([\'\"])[^\'\"]+\1")
_SODIPODI_NAMEDVIEW_RE = re.compile(
    r"<sodipodi:namedview[\s\S]*?</sodipodi:namedview>|<sodipodi:namedview[^>]*/>",
    re.IGNORECASE,
)
_NAMESPACED_ATTR_RE = re.compile(
    r"\s(?:inkscape|sodipodi):[\w:-]+\s*=\s*([\'\"])[^\'\"]+\1"
)
_ROOT_GEOMETRY_ATTR_RE = re.compile(
    r"\s(?:width|height|viewBox)\s*=\s*([\'\"])[^\'\"]+\1"
)
_ID_RE = re.compile(r"\sid=(['\"])[^'\"]+\1")
_METADATA_RE = re.compile(r"<metadata[\s\S]*?</metadata>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_HREF_RE = re.compile(r"\s(?:xlink:href|href)\s*=\s*(['\"])#[^'\"]+\1")
_URL_REF_ATTR_RE = re.compile(r"\s[\w:-]+\s*=\s*(['\"])url\(#.*?\)\1")


def strip_svg_xml_declaration(svg_text: str) -> str:
    """Strip optional XML prolog / doctype from an SVG string.

    Many SVG converters emit an XML declaration. That prolog is legal XML but
    can break consumers that expect an inline ``<svg ...>`` root. Removing it is
    safe for typical inline usage and does not alter the SVG element tree.
    """

    if not svg_text:
        return svg_text

    out = _XML_DECL_RE.sub("", svg_text, count=1)
    out = _DOCTYPE_RE.sub("", out, count=1)
    return out.lstrip("\n")


def normalize_svg(svg: str) -> str:
    """
    Normalize SVG text to reduce nondeterministic diffs.

    Notes:
    - This normalization is intended for text comparison, not rendering.
    - Internal ID/reference wiring is stripped to avoid converter-specific noise.
    """
    svg = _METADATA_RE.sub("", svg)
    svg = _SODIPODI_NAMEDVIEW_RE.sub("", svg)
    svg = _XMLNS_RE.sub("", svg)
    svg = _NAMESPACED_ATTR_RE.sub("", svg)
    svg = _ROOT_GEOMETRY_ATTR_RE.sub("", svg)
    svg = _COMMENT_RE.sub("", svg)
    svg = _ID_RE.sub("", svg)
    svg = _HREF_RE.sub("", svg)
    svg = _URL_REF_ATTR_RE.sub("", svg)
    svg = re.sub(r"\s+", " ", svg).strip()
    return svg
