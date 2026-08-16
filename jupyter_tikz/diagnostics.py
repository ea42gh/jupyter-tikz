from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ToolchainFailureArtifacts(Protocol):
    @property
    def stdout_path(self) -> Path: ...

    @property
    def stderr_path(self) -> Path: ...

    @property
    def returncodes(self) -> list[int]: ...


def tail_text(path: Path, *, limit_chars: int) -> str:
    """Read the tail of a text file for diagnostics."""

    try:
        if not path.exists():
            return f"<missing: {path.name}>"
        txt = path.read_text(errors="replace")
    except Exception:
        return f"<unreadable: {path.name}>"
    if len(txt) <= int(limit_chars):
        return txt
    return txt[-int(limit_chars) :]


def format_toolchain_failure(
    artifacts: ToolchainFailureArtifacts,
    *,
    workdir: Path,
    output_stem: str,
) -> str:
    """Format a RenderError message with actionable diagnostics."""

    last_rc = artifacts.returncodes[-1] if artifacts.returncodes else "n/a"
    stdout_tail = tail_text(artifacts.stdout_path, limit_chars=6000)
    stderr_tail = tail_text(artifacts.stderr_path, limit_chars=4000)
    log_tail = tail_text(workdir / f"{output_stem}.log", limit_chars=8000)

    # Keep this message stable: tests assert specific substrings.
    return (
        "Toolchain execution failed.\n"
        f"Artifacts kept at: {workdir}.\n"
        f"See stdout at: {artifacts.stdout_path}\n"
        f"See stderr at: {artifacts.stderr_path}\n"
        f"Last returncode: {last_rc}.\n"
        "---- stdout tail ----\n"
        f"{stdout_tail}\n\n"
        "---- stderr tail ----\n"
        f"{stderr_tail}\n\n"
        "---- latex log tail ----\n"
        f"{log_tail}"
    )
