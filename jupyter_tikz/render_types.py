from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from jupyter_tikz.svg_normalize import strip_svg_xml_declaration


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    returncodes: List[int]
    stdout: List[str]
    stderr: List[str]
    svg_text: str | None

    @property
    def stdout_text(self) -> str:
        return "".join(self.stdout)

    @property
    def stderr_text(self) -> str:
        return "".join(self.stderr)


@dataclass(frozen=True)
class RenderArtifacts:
    workdir: Path
    tex_path: Path
    pdf_path: Path | None
    svg_path: Path | None
    stdout_path: Path
    stderr_path: Path
    returncodes: List[int]

    def read_svg(self, *, strip_xml_declaration: bool = True) -> str:
        if self.svg_path is None or not self.svg_path.exists():
            raise RenderError("SVG output not produced")
        txt = self.svg_path.read_text(errors="replace")
        return strip_svg_xml_declaration(txt) if strip_xml_declaration else txt
