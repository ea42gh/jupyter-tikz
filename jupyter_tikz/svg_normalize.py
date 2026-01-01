import re

_ID_RE       = re.compile(r'\sid="[^"]*"')
_METADATA_RE = re.compile(r'<metadata[\s\S]*?</metadata>', re.IGNORECASE)
_COMMENT_RE  = re.compile(r'<!--[\s\S]*?-->')


def normalize_svg(svg: str) -> str:
    """
    Normalize SVG text to reduce nondeterministic diffs.
    """
    svg = _METADATA_RE.sub("", svg)
    svg = _COMMENT_RE.sub("", svg)
    svg = _ID_RE.sub("", svg)
    svg = re.sub(r"\s+", " ", svg).strip()
    return svg

