import pytest


def test_resolve_crop_mode_defaults():
    from jupyter_tikz.executor import resolve_crop_mode
    from jupyter_tikz.toolchains import PDFTEX_DVISVGM, PDFTEX_PDFTOCAIRO

    # Legacy default (no env var): tight across toolchains to preserve historical outputs.
    assert resolve_crop_mode(None, PDFTEX_PDFTOCAIRO) == "tight"
    assert resolve_crop_mode(None, PDFTEX_DVISVGM) == "tight"
    assert resolve_crop_mode("none", PDFTEX_PDFTOCAIRO) == "none"
    assert resolve_crop_mode("page", PDFTEX_DVISVGM) == "page"


def test_resolve_crop_policy_distinguishes_default_vs_explicit():
    from jupyter_tikz.executor import resolve_crop_policy
    from jupyter_tikz.toolchains import PDFTEX_DVISVGM, PDFTEX_PDFTOCAIRO

    mode, enforce = resolve_crop_policy(None, PDFTEX_PDFTOCAIRO)
    assert mode == "tight"
    assert enforce is True

    mode, enforce = resolve_crop_policy("tight", PDFTEX_PDFTOCAIRO)
    assert mode == "tight"
    assert enforce is True

    mode, enforce = resolve_crop_policy(None, PDFTEX_DVISVGM)
    assert mode == "tight"
    assert enforce is False


def test_padding_normalization_forms():
    from jupyter_tikz.svg_box import normalize_padding

    assert normalize_padding(3).left == 3
    assert normalize_padding((2, 5)).top == 5
    assert normalize_padding((1, 2, 3, 4)).bottom == 4
    p = normalize_padding({"left": 1, "top": 2})
    assert (p.left, p.right, p.top, p.bottom) == (1, 0, 2, 0)


def test_cache_separates_base_svg_from_padding(monkeypatch):
    """Changing padding should not re-run the base render."""
    import jupyter_tikz.executor as ex
    from jupyter_tikz import render_svg

    ex.clear_render_cache()

    calls = {"n": 0}

    def fake_uncached(
        tex_source,
        toolchain_name,
        *,
        output_stem,
        crop_mode,
        enforce_tight_crop,
        exact_bbox,
    ):
        calls["n"] += 1
        return '<svg viewBox="0 0 10 10"></svg>'

    monkeypatch.setattr(ex, "_render_base_svg_uncached", fake_uncached)

    tex = "\\documentclass{article}\\begin{document}x\\end{document}"

    svg1 = render_svg(
        tex, toolchain_name="pdftex_pdftocairo", crop="page", padding=0, cache=True
    )
    svg2 = render_svg(
        tex,
        toolchain_name="pdftex_pdftocairo",
        crop="page",
        padding={"left": 2},
        cache=True,
    )
    svg3 = render_svg(
        tex,
        toolchain_name="pdftex_pdftocairo",
        crop="page",
        padding={"left": 5},
        cache=True,
    )

    assert calls["n"] == 1
    assert 'viewBox="0.0 0.0 10.0 10.0"' in svg1 or 'viewBox="0 0 10 10"' in svg1
    assert 'viewBox="-2.0 0.0 12.0 10.0"' in svg2
    assert 'viewBox="-5.0 0.0 15.0 10.0"' in svg3


def test_cache_can_be_disabled(monkeypatch):
    import jupyter_tikz.executor as ex
    from jupyter_tikz import render_svg

    ex.clear_render_cache()

    calls = {"n": 0}

    def fake_run_toolchain_in_dir(
        toolchain,
        tex_source,
        workdir,
        output_stem,
        *,
        crop_mode,
        enforce_tight_crop,
        exact_bbox,
        padding,
    ):
        calls["n"] += 1
        # minimal artifacts that satisfy render_svg
        from pathlib import Path

        workdir = Path(workdir)
        tex_path = workdir / f"{output_stem}.tex"
        tex_path.write_text(tex_source)
        svg_path = workdir / f"{output_stem}.svg"
        svg_path.write_text('<svg viewBox="0 0 10 10"></svg>')
        stdout_path = workdir / f"{output_stem}.stdout.txt"
        stderr_path = workdir / f"{output_stem}.stderr.txt"
        stdout_path.write_text("")
        stderr_path.write_text("")
        return ex.RenderArtifacts(
            workdir=workdir,
            tex_path=tex_path,
            pdf_path=None,
            svg_path=svg_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            returncodes=[0],
        )

    monkeypatch.setattr(ex, "_run_toolchain_in_dir", fake_run_toolchain_in_dir)

    tex = "\\documentclass{article}\\begin{document}x\\end{document}"

    render_svg(
        tex, toolchain_name="pdftex_pdftocairo", crop="page", padding=0, cache=False
    )
    render_svg(
        tex, toolchain_name="pdftex_pdftocairo", crop="page", padding=0, cache=False
    )

    assert calls["n"] == 2
