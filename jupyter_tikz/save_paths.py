from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from .paths import ensure_within_root, validate_user_output_path


def resolve_save_destination(
    dest: str,
    ext: Literal["tikz", "tex", "png", "svg", "pdf"],
) -> Path:
    """Resolve and validate a user output destination for saved artifacts."""
    dest_path = validate_user_output_path(dest, field_name="save destination")

    save_root: Path | None = None
    savedir = os.environ.get("JUPYTER_TIKZ_SAVEDIR")
    if savedir:
        save_root = validate_user_output_path(
            savedir, field_name="JUPYTER_TIKZ_SAVEDIR"
        )
        dest_path = save_root / dest_path

    dest_path = dest_path.resolve()
    if save_root is not None:
        ensure_within_root(dest_path, save_root, field_name="save destination")

    if dest_path.suffix != f".{ext}":
        dest_path = dest_path.with_suffix(dest_path.suffix + f".{ext}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    return dest_path
