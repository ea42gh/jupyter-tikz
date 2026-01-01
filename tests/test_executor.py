from pathlib import Path
from jupyter_tikz.executor import build_commands
from jupyter_tikz.toolchains import TOOLCHAINS


def test_build_commands_pdftocairo():
    tc = TOOLCHAINS["pdftex_pdftocairo"]
    tex = Path("example.tex")

    cmds = build_commands(tc, tex, output_stem="example")

    assert len(cmds) == 2
    assert cmds[0][:2] == ["latexmk", "-pdf"]
    assert cmds[0][-1] == "example.tex"

    assert cmds[1][0] in ("pdftocairo",)
    assert cmds[1][-2:] == ["example.pdf", "example.svg"]

