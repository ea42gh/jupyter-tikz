from __future__ import annotations


class JupyterTikzError(Exception):
    """Base exception for jupyter_tikz runtime/configuration errors."""


class InvalidToolchainError(JupyterTikzError, ValueError):
    """Raised when a requested toolchain is unknown or unsupported."""


class InvalidOutputStemError(JupyterTikzError, ValueError):
    """Raised when an output stem is unsafe or malformed."""


class InvalidPathError(JupyterTikzError, ValueError):
    """Raised when a user-provided path is unsafe or invalid."""
