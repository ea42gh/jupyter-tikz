import os
from pathlib import Path

import jupyter_tikz.executor as ex
from jupyter_tikz.executor import _find_svg_output_path, build_commands
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


def test_find_svg_output_path_prefers_exact_svg(tmp_path):
    (tmp_path / "out-1.svg").write_text("<svg/>")
    (tmp_path / "out.svg").write_text("<svg id='exact'/>")

    p = _find_svg_output_path(tmp_path, "out")
    assert p == tmp_path / "out.svg"


def test_find_svg_output_path_chooses_lowest_numeric_suffix(tmp_path):
    (tmp_path / "out-10.svg").write_text("<svg id='10'/>")
    (tmp_path / "out-2.svg").write_text("<svg id='2'/>")
    (tmp_path / "out-1.svg").write_text("<svg id='1'/>")

    p = _find_svg_output_path(tmp_path, "out")
    assert p == tmp_path / "out-1.svg"


def test_find_svg_output_path_falls_back_to_lexicographic(tmp_path):
    (tmp_path / "out-foo.svg").write_text("<svg id='foo'/>")
    (tmp_path / "out-bar.svg").write_text("<svg id='bar'/>")

    p = _find_svg_output_path(tmp_path, "out")
    assert p == tmp_path / "out-bar.svg"


def test_build_subprocess_env_includes_source_cwd_by_default(monkeypatch):
    monkeypatch.delenv("JUPYTER_TIKZ_DISABLE_CWD_TEXINPUTS", raising=False)
    monkeypatch.setenv("TEXINPUTS", "foo")
    source_cwd = Path("repo/notebooks").resolve()

    env = ex._build_subprocess_env(source_cwd=source_cwd)

    assert env["TEXINPUTS"] == os.pathsep.join([".", str(source_cwd), "foo"])


def test_build_subprocess_env_can_disable_cwd_injection(monkeypatch):
    monkeypatch.setenv("JUPYTER_TIKZ_DISABLE_CWD_TEXINPUTS", "1")
    monkeypatch.setenv("TEXINPUTS", "foo")

    env = ex._build_subprocess_env(source_cwd=Path("repo/notebooks").resolve())

    assert env["TEXINPUTS"] == "foo"
