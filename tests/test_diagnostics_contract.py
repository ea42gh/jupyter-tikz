import json

import pytest

from jupyter_tikz import TikZMagics


@pytest.fixture
def tikz_magic(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    return TikZMagics()


def _assert_diag_row_shape(row: dict):
    assert set(row.keys()) == {
        "name",
        "available",
        "latex_bin",
        "latex_path",
        "svg_bin",
        "svg_path",
    }
    assert isinstance(row["name"], str)
    assert isinstance(row["available"], bool)
    assert isinstance(row["latex_bin"], str)
    assert isinstance(row["svg_bin"], str)
    assert row["latex_path"] is None or isinstance(row["latex_path"], str)
    assert row["svg_path"] is None or isinstance(row["svg_path"], str)


def test_diagnose_json_contract_all_toolchains(tikz_magic, monkeypatch, capsys):
    monkeypatch.setattr(
        "jupyter_tikz.magic.check_toolchains",
        lambda: {
            "pdftex_pdftocairo": {
                "name": "pdftex_pdftocairo",
                "available": True,
                "latex_bin": "latexmk",
                "latex_path": "/bin/latexmk",
                "svg_bin": "pdftocairo",
                "svg_path": "/bin/pdftocairo",
            },
            "xelatex_pdftocairo": {
                "name": "xelatex_pdftocairo",
                "available": False,
                "latex_bin": "latexmk",
                "latex_path": None,
                "svg_bin": "pdftocairo",
                "svg_path": "/bin/pdftocairo",
            },
        },
    )

    res = tikz_magic.tikz("--diagnose -j")
    out, err = capsys.readouterr()

    assert res is None
    assert err == ""
    payload = json.loads(out)
    assert set(payload.keys()) == {"requested_toolchain", "toolchains"}
    assert payload["requested_toolchain"] is None
    assert isinstance(payload["toolchains"], list)
    assert len(payload["toolchains"]) == 2
    for row in payload["toolchains"]:
        _assert_diag_row_shape(row)


def test_diagnose_json_contract_single_toolchain(tikz_magic, monkeypatch, capsys):
    monkeypatch.setattr(
        "jupyter_tikz.magic.check_toolchain",
        lambda name: {
            "name": name,
            "available": True,
            "latex_bin": "latexmk",
            "latex_path": "/bin/latexmk",
            "svg_bin": "pdftocairo",
            "svg_path": "/bin/pdftocairo",
        },
    )

    res = tikz_magic.tikz("--diagnose --toolchain pdftex_pdftocairo --json")
    out, err = capsys.readouterr()

    assert res is None
    assert err == ""
    payload = json.loads(out)
    assert payload["requested_toolchain"] == "pdftex_pdftocairo"
    assert isinstance(payload["toolchains"], list)
    assert len(payload["toolchains"]) == 1
    _assert_diag_row_shape(payload["toolchains"][0])
