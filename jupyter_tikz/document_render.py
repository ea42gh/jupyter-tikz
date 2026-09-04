from __future__ import annotations

from .executor import render_document


def run_latex(*args, **kwargs):
    """Compatibility wrapper for the historical TexDocument API."""

    return render_document(*args, **kwargs)
