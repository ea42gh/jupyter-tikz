from pathlib import Path

from jupyter_tikz import TikZMagics


def _normalize(s: str) -> str:
    return s.replace("\r\n", "\n")


def test_tikz_magic_help_snapshot():
    got = _normalize(TikZMagics.tikz.parser.format_help())
    expected = _normalize(
        (Path(__file__).parent / "snapshots" / "tikz_magic_help.txt").read_text()
    )
    assert got == expected
