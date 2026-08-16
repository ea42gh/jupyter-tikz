from __future__ import annotations

import os
import subprocess
from hashlib import md5
from pathlib import Path
from typing import List

from jupyter_tikz.toolchains import Toolchain


def env_truthy(name: str) -> bool:
    """Return True if an environment variable is set to a truthy value."""
    v = os.environ.get(name)
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "on"}


def build_subprocess_env(*, source_cwd: Path | None = None) -> dict[str, str]:
    """Build subprocess env with a TeX search path that includes caller CWD.

    By default we keep executor builds isolated in a temp workdir, but still
    allow relative TeX inputs (e.g. ``\\input{grid.tikz}``, PGFPlots
    ``table {data.tsv}``) from the notebook/project directory.

    Set ``JUPYTER_TIKZ_DISABLE_CWD_TEXINPUTS=1`` to opt out of this behavior.
    """

    env = os.environ.copy()
    if env_truthy("JUPYTER_TIKZ_DISABLE_CWD_TEXINPUTS"):
        return env

    cwd = str((source_cwd or Path.cwd()).resolve())
    texinputs = env.get("TEXINPUTS", "")
    prefix = os.pathsep.join([".", cwd])
    if texinputs:
        env["TEXINPUTS"] = os.pathsep.join([prefix, texinputs])
    else:
        # Keep the trailing separator so TeX also searches its default paths.
        env["TEXINPUTS"] = prefix + os.pathsep
    return env


_LATEX_RERUN_MARKERS: tuple[str, ...] = (
    "Label(s) may have changed. Rerun to get cross-references right.",
    "Rerun to get citations correct.",
    "Rerun to get outlines right",
    "rerunfilecheck Warning: File",
    "There were undefined references.",
)


def file_digest(path: Path) -> str | None:
    try:
        if not path.exists():
            return None
        return md5(path.read_bytes()).hexdigest()
    except Exception:
        return None


def latex_requests_rerun(stdout: str, stderr: str, log_path: Path) -> bool:
    haystacks = [stdout or "", stderr or ""]
    try:
        if log_path.exists():
            haystacks.append(log_path.read_text(errors="replace"))
    except Exception:
        pass
    return any(marker in hay for hay in haystacks for marker in _LATEX_RERUN_MARKERS)


def run_latex_passes(
    toolchain: Toolchain,
    tex_path: Path,
    *,
    workdir: Path,
    env: dict[str, str],
) -> tuple[List[int], List[str], List[str]]:
    returncodes: List[int] = []
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    aux_path = workdir / f"{tex_path.stem}.aux"
    log_path = workdir / f"{tex_path.stem}.log"
    prev_aux_digest: str | None = None

    for pass_num in range(max(1, int(toolchain.max_passes))):
        proc = subprocess.run(
            list(toolchain.latex_cmd) + [tex_path.name],
            cwd=str(workdir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        returncodes.append(proc.returncode)
        stdout_chunks.append(proc.stdout)
        stderr_chunks.append(proc.stderr)

        if proc.returncode != 0:
            break

        aux_digest = file_digest(aux_path)
        rerun = latex_requests_rerun(proc.stdout, proc.stderr, log_path)
        if pass_num + 1 >= max(1, int(toolchain.max_passes)):
            break
        if not rerun and aux_digest == prev_aux_digest:
            break
        prev_aux_digest = aux_digest

    return returncodes, stdout_chunks, stderr_chunks


# Compatibility aliases for older executor-internal imports.
_build_subprocess_env = build_subprocess_env
_file_digest = file_digest
_latex_requests_rerun = latex_requests_rerun
_run_latex_passes = run_latex_passes
_env_truthy = env_truthy
