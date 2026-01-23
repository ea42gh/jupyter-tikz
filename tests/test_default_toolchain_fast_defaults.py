import os


def _fake_which(available: set[str]):
    """Return a ``shutil.which`` replacement limited to the given basenames."""

    def which(cmd: str):
        base = os.path.basename(cmd)
        return f"/bin/{base}" if base in available else None

    return which


def test_resolve_toolchain_name_legacy_defaults(monkeypatch):
    import jupyter_tikz.executor as ex

    # latexmk and all converters are "available".
    monkeypatch.setattr(ex.shutil, "which", _fake_which({"latexmk", "pdftocairo", "pdf2svg", "dvisvgm"}))
    monkeypatch.delenv("JUPYTER_TIKZ_FAST_DEFAULTS", raising=False)
    monkeypatch.delenv("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN", raising=False)

    ex.set_default_toolchain_name(None)
    assert ex.resolve_toolchain_name(None) == "pdftex_pdftocairo"


def test_resolve_toolchain_name_fast_defaults(monkeypatch):
    import jupyter_tikz.executor as ex

    monkeypatch.setattr(ex.shutil, "which", _fake_which({"latexmk", "pdftocairo", "dvisvgm"}))
    monkeypatch.setenv("JUPYTER_TIKZ_FAST_DEFAULTS", "1")
    monkeypatch.delenv("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN", raising=False)

    ex.set_default_toolchain_name(None)
    assert ex.resolve_toolchain_name(None) == "pdftex_dvisvgm"


def test_default_toolchain_env_overrides_fast_defaults(monkeypatch):
    import jupyter_tikz.executor as ex

    monkeypatch.setattr(ex.shutil, "which", _fake_which({"latexmk", "pdftocairo", "dvisvgm"}))
    monkeypatch.setenv("JUPYTER_TIKZ_FAST_DEFAULTS", "1")
    monkeypatch.setenv("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN", "xelatex_pdf2svg")

    ex.set_default_toolchain_name(None)
    assert ex.resolve_toolchain_name(None) == "xelatex_pdf2svg"


def test_programmatic_override_beats_env_and_fast_defaults(monkeypatch):
    import jupyter_tikz.executor as ex

    monkeypatch.setattr(ex.shutil, "which", _fake_which({"latexmk", "pdftocairo", "dvisvgm"}))
    monkeypatch.setenv("JUPYTER_TIKZ_FAST_DEFAULTS", "1")
    monkeypatch.setenv("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN", "pdftex_dvisvgm")

    ex.set_default_toolchain_name("xelatex_pdftocairo")
    try:
        assert ex.resolve_toolchain_name(None) == "xelatex_pdftocairo"
    finally:
        ex.set_default_toolchain_name(None)


def test_resolve_toolchain_name_fallbacks_to_first_registered(monkeypatch):
    import jupyter_tikz.executor as ex

    monkeypatch.setattr(ex.shutil, "which", _fake_which(set()))
    monkeypatch.delenv("JUPYTER_TIKZ_FAST_DEFAULTS", raising=False)
    monkeypatch.delenv("JUPYTER_TIKZ_DEFAULT_TOOLCHAIN", raising=False)

    ex.set_default_toolchain_name(None)
    assert ex.resolve_toolchain_name(None) == next(iter(ex.TOOLCHAINS.keys()))
