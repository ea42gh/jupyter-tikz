from __future__ import annotations

from os import PathLike
from pathlib import Path

from .errors import InvalidPathError


def _contains_parent_ref(path: Path) -> bool:
    return ".." in path.parts


def validate_user_output_path(
    value: str | Path | PathLike[str], *, field_name: str
) -> Path:
    """Validate user-provided output paths used for local file writes."""
    p = Path(value)
    if not str(p).strip():
        raise InvalidPathError(f"{field_name} must be a non-empty path")
    if "\x00" in str(p):
        raise InvalidPathError(f"{field_name} must not contain NUL bytes")
    if not p.is_absolute() and _contains_parent_ref(p):
        raise InvalidPathError(f"{field_name} must not contain '..' path segments")
    return p


def ensure_within_root(path: Path, root: Path, *, field_name: str) -> None:
    """Ensure an output path stays under an explicit save root."""
    rp = path.resolve()
    rr = root.resolve()
    try:
        rp.relative_to(rr)
    except ValueError:
        raise InvalidPathError(f"{field_name} resolves outside JUPYTER_TIKZ_SAVEDIR")
