from __future__ import annotations

import os
import re

from .errors import InvalidOutputStemError

_OUTPUT_STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_output_stem(output_stem: str) -> str:
    """Validate an artifact output stem used for local filenames.

    The stem must be a safe filename token (not a path) to avoid path
    traversal and cross-directory writes.
    """
    stem = str(output_stem or "").strip()
    if not stem:
        raise InvalidOutputStemError("output_stem must be a non-empty string")
    if os.path.sep in stem or (os.path.altsep and os.path.altsep in stem):
        raise InvalidOutputStemError("output_stem must not contain path separators")
    if stem in {".", ".."}:
        raise InvalidOutputStemError("output_stem must not be '.' or '..'")
    if not _OUTPUT_STEM_RE.fullmatch(stem):
        raise InvalidOutputStemError(
            "output_stem may contain only letters, digits, '.', '_' and '-', "
            "and must start with a letter or digit"
        )
    return stem
