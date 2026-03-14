from pathlib import Path

import pytest

from jupyter_tikz.save_paths import resolve_save_destination


def test_resolve_save_destination_adds_extension(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = resolve_save_destination("outputs/demo", "svg")
    assert out == (tmp_path / "outputs" / "demo.svg")


def test_resolve_save_destination_respects_savedir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    save_root = tmp_path / "savedir"
    monkeypatch.setenv("JUPYTER_TIKZ_SAVEDIR", str(save_root))
    out = resolve_save_destination("nested/demo", "pdf")
    assert out == (save_root / "nested" / "demo.pdf")


def test_resolve_save_destination_rejects_parent_ref(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="save destination"):
        resolve_save_destination("../bad", "png")
