import re

_ID_RE = re.compile(r"\sid=(['\"])[^'\"]+\1")
_METADATA_RE = re.compile(r'<metadata[\s\S]*?</metadata>', re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_HREF_RE = re.compile(r"\s(?:xlink:href|href)\s*=\s*(['\"])#[^'\"]+\1")
_URL_REF_ATTR_RE = re.compile(r"\s[\w:-]+\s*=\s*(['\"])url\(#.*?\)\1")


def normalize_svg(svg: str) -> str:
    """
    Normalize SVG text to reduce nondeterministic diffs.

    Notes:
    - This normalization is intended for text comparison, not rendering.
    - Internal ID/reference wiring is stripped to avoid converter-specific noise.
    """
    svg = _METADATA_RE.sub("", svg)
    svg = _COMMENT_RE.sub("", svg)
    svg = _ID_RE.sub("", svg)
    svg = _HREF_RE.sub("", svg)
    svg = _URL_REF_ATTR_RE.sub("", svg)
    svg = re.sub(r"\s+", " ", svg).strip()
    return svg
