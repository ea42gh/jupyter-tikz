from pathlib import Path

import pytest

from jupyter_tikz import TexDocument, TexFragment, TikZMagics
from jupyter_tikz.jupyter_tikz import (
    _EXTRAS_CONFLITS_ERR,
    _INPUT_TYPE_CONFLIT_ERR,
    _PRINT_CONFLICT_ERR,
)


@pytest.fixture
def tikz_magic(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    return TikZMagics()


@pytest.fixture
def tikz_magic_mock(mocker, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    tikz_magic = TikZMagics()

    def run_latex_mock(*args, **kwargs):
        _ = kwargs
        return "dummy_image"

    # def save_mock(*args, **kwargs):
    #     _ = args
    #     _ = kwargs
    #     return args

    # def jinja_mock(*args, **kwargs):
    #     _ = args
    #     _ = kwargs
    #     return None

    mocker.patch.object(TexDocument, "run_latex", side_effect=run_latex_mock)
    # mocker.patch.object(TexFragment, "_build_full_latex", return_value="dummy_code")
    mocker.patch.object(
        TexFragment, "_build_standalone_preamble", return_value="dummy preamble"
    )
    mocker.patch.object(TikZMagics, "_render_with_executor", return_value="dummy_image")
    # mocker.patch.object(TexDocument, "_render_jinja", side_effect=jinja_mock)

    return tikz_magic


def test_show_help_on_empy_code(tikz_magic, capsys):
    # Arrange
    line = ""

    # Act
    tikz_magic.tikz(line)  # magic_line

    # Assert
    _, err = capsys.readouterr()
    assert 'Use "%tikz?" for help\n' == err


EXAMPLE_TIKZ_JINJA_TEMPLATE = """\\begin{tikzpicture}
    \\node[draw] at (0,0) {Hello, (* name *)!};
\\end{tikzpicture}
"""

EXAMPLE_TIKZ_RENDERED_TEMPLATE = """\\begin{tikzpicture}
    \\node[draw] at (0,0) {Hello, World!};
\\end{tikzpicture}
"""


def test_print_jinja(tikz_magic_mock, capsys):
    # Arrange
    line = "-pj"
    cell = EXAMPLE_TIKZ_JINJA_TEMPLATE

    # Act
    tikz_magic_mock.tikz(line, cell=cell, local_ns={"name": "World"})  # magic_line

    # Assert
    out, err = capsys.readouterr()
    assert out.strip() == EXAMPLE_TIKZ_RENDERED_TEMPLATE.strip()


@pytest.mark.needs_latex
@pytest.mark.needs_pdftocairo
def test_print_jinja_no_mocks(tikz_magic, capsys):
    # Arrange
    line = "-pj"
    cell = EXAMPLE_TIKZ_JINJA_TEMPLATE

    # Act
    tikz_magic.tikz(line, cell=cell, local_ns={"name": "World"})  # magic_line

    # Assert
    out, err = capsys.readouterr()
    assert out.strip() == EXAMPLE_TIKZ_RENDERED_TEMPLATE.strip()


EXAMPLE_TIKZ_BASIC_STANDALONE = r"\draw[fill=blue] (0, 0) rectangle (1, 1);"

RES_TIKZ_BASIC_STANDALONE = r"""\documentclass{standalone}
\usepackage{tikz}
\begin{document}
    \begin{tikzpicture}
        \draw[fill=blue] (0, 0) rectangle (1, 1);
    \end{tikzpicture}
\end{document}"""


def test_print_tex(tikz_magic_mock, capsys):
    # Arrange
    line = "-pt -as=full -sv=var -g"
    cell = "EXAMPLE_TIKZ"

    # Act
    tikz_magic_mock.tikz(line, cell)  # magic_line

    # Assert
    out, err = capsys.readouterr()
    assert out.strip() == cell.strip()


@pytest.mark.needs_latex
@pytest.mark.needs_pdftocairo
def test_print_tex_no_mocks(tikz_magic, capsys):
    # Arrange
    line = "-pt -as=tikz"
    cell = EXAMPLE_TIKZ_BASIC_STANDALONE

    expected_res = RES_TIKZ_BASIC_STANDALONE

    # Act
    tikz_magic.tikz(line, cell)  # magic_line

    # Assert
    out, err = capsys.readouterr()
    assert out.strip() == expected_res.strip()


def test_image_none(tikz_magic_mock, mocker, capsys):
    # Arrange
    line = ""
    cell = "any cell content"
    mocker.patch.object(TikZMagics, "_render_with_executor", return_value=None)

    # Act
    res = tikz_magic_mock.tikz(line, cell)

    # Assert
    assert res is None


TIKZ_CODE = r"""\begin{tikzpicture}
    \draw[fill=blue] (0, 0) rectangle (1, 1);
\end{tikzpicture}"""


# def test_save_tikz(tikz_magic_mock):
#     # Arrange
#     line = "-s=any_file.tikz"
#     cell = TIKZ_CODE

#     # Act
#     tikz_magic_mock.tikz(line, cell)

#     # Assert
#     assert "any_file.tikz" in tikz_magic_mock.saved_path


# @pytest.mark.needs_latex
# @pytest.mark.needs_pdftocairo
# def test_save_tikz(tikz_magic, tmp_path, monkeypatch, mocker):
#     monkeypatch.chdir(tmp_path)

#     # Arrange
#     file_name = "any_file.tikz"
#     file_path = tmp_path / "any_file.tikz"

#     line = f"-s={file_name}"
#     cell = TIKZ_CODE

#     # Act
#     tikz_magic.tikz(line, cell)
#     spy = mocker.spy(tikz_magic, "TexDocument")

#     # Assert
#     assert file_path.read_text() == cell
#     assert "any_file.tex" in tikz_magic.saved_path


# =================== Test input type ===================
@pytest.mark.parametrize(
    "input_type", ["fulldocument", "standalonedocument", "tikz-picture", "banana"]
)
def test_invalid_input_type(input_type, tikz_magic, capsys):
    # Arrange
    line = f"--input-type {input_type}"
    cell = "any cell content"

    # Act
    tikz_magic.tikz(line, cell)

    # Assert
    _, err = capsys.readouterr()
    assert tikz_magic._get_input_type(input_type) is None
    assert (
        err
        == f"`{input_type}` is not a valid input type. Valid input types are `full-document`, `standalone-document`, or `tikzpicture`.\n"
    )


@pytest.mark.parametrize(
    "input_type, expected_input_type",
    [
        ("full-document", "full-document"),
        ("full", "full-document"),
        ("f", "full-document"),
        ("standalone-document", "standalone-document"),
        ("standalone", "standalone-document"),
        ("s", "standalone-document"),
        ("tikzpicture", "tikzpicture"),
        ("tikz", "tikzpicture"),
        ("t", "tikzpicture"),
    ],
)
def test_valid_input_type(tikz_magic_mock, input_type, expected_input_type):
    # Arrange
    line = f"--input-type {input_type}"
    cell = "any cell content"

    # Act
    res = tikz_magic_mock.tikz(line, cell)

    # Assert
    assert tikz_magic_mock._get_input_type(input_type) == expected_input_type


@pytest.mark.parametrize(
    "input_type, expected_input_type",
    [
        ("full-document", "full-document"),
        ("full", "full-document"),
        ("f", "full-document"),
        ("standalone-document", "standalone-document"),
        ("standalone", "standalone-document"),
        ("s", "standalone-document"),
        ("tikzpicture", "tikzpicture"),
        ("tikz", "tikzpicture"),
        ("t", "tikzpicture"),
    ],
)
def test_tex_obj_type(tikz_magic_mock, input_type, expected_input_type):
    # Arrange
    line = f"-as={input_type}"
    code = "any code"

    # Act
    tikz_magic_mock.tikz(line, code)

    # Assert
    assert tikz_magic_mock.input_type == expected_input_type

    if tikz_magic_mock.input_type != "full-document":
        assert isinstance(tikz_magic_mock.tex_obj, TexFragment)
        assert tikz_magic_mock.tex_obj.template == expected_input_type
    else:
        assert isinstance(tikz_magic_mock.tex_obj, TexDocument)


@pytest.mark.parametrize(
    "params, expected_input_type",
    [
        ("-f", "full-document"),
        ("-i", "tikzpicture"),
    ],
)
def test_alternative_tex_obj_type(tikz_magic_mock, params, expected_input_type):
    # Arrange
    line = params
    code = "any code"

    # Act
    tikz_magic_mock.tikz(line, code)

    # Assert
    assert tikz_magic_mock.input_type == expected_input_type


@pytest.mark.parametrize(
    "key, params, expected_output",
    [
        (
            "latex_preamble",
            "-p "
            + '"\\usepackage{tikz}\\usepackage{xcolor}\\definecolor{my_color}{RGB}{0,238,255}"',
            "\\usepackage{tikz}\\usepackage{xcolor}\\definecolor{my_color}{RGB}{0,238,255}",
        ),
        (
            "latex_preamble",
            "-p " + '"\\usepackage{tikz}\n\\definecolor{my_color}{RGB}{0,238,255}\n"',
            "\\usepackage{tikz}\n\\definecolor{my_color}{RGB}{0,238,255}\n",
        ),
        ("tex_packages", "-t " + '"amsfonts,amsmath"', "amsfonts,amsmath"),
        ("tex_packages", "-t " + "amsfonts,amsmath", "amsfonts,amsmath"),
        ("tex_packages", "-t " + '"amsfonts, amsmath"', "amsfonts, amsmath"),
        ("tikz_libraries", "-l " + '"calc, arrows"', "calc, arrows"),
        ("tikz_libraries", "-l " + "calc,arrows", "calc,arrows"),
        ("pgfplots_libraries", "-lp " + '"groupplots,external"', "groupplots,external"),
        ("tex_args", "-ta=" + '"-shell-escape"', "-shell-escape"),
    ],
)
def test_remove_quotation_marks_from_strings_args(
    tikz_magic_mock, key, params, expected_output
):
    # Arrange
    line = params
    code = "any code"

    # Act
    tikz_magic_mock.tikz(line, code, local_ns={})

    # Assert
    assert tikz_magic_mock.args[key] == expected_output


def test_keep_temp_bool_flag_parses(tikz_magic_mock):
    tikz_magic_mock.tikz("-k -nc", "any code")
    assert tikz_magic_mock.args["keep_temp"] is True


def test_keep_temp_optional_dir_parses(tikz_magic_mock):
    tikz_magic_mock.tikz("--keep-temp outputs/tmp -nc", "any code")
    assert tikz_magic_mock.args["keep_temp"] == "outputs/tmp"


def test_output_stem_parses(tikz_magic_mock):
    tikz_magic_mock.tikz("--output-stem my_render -nc", "any code")
    assert tikz_magic_mock.args["output_stem"] == "my_render"


def test_keep_temp_optional_dir_routes_executor_output_dir(
    tikz_magic, monkeypatch, tmp_path
):
    captured: dict[str, Path] = {}

    class _Artifacts:
        def __init__(self, workdir: Path):
            self.tex_path = workdir / "dummy.tex"
            self.pdf_path = None
            self.svg_path = workdir / "dummy.svg"

        def read_svg(self, *, strip_xml_declaration=True):
            _ = strip_xml_declaration
            return "<svg viewBox='0 0 1 1'></svg>"

    def fake_render_svg_with_artifacts(
        tex_source, *, output_dir, toolchain_name, output_stem
    ):
        _ = tex_source, toolchain_name, output_stem
        out = Path(output_dir)
        captured["output_dir"] = out
        out.mkdir(parents=True, exist_ok=True)
        return _Artifacts(out)

    monkeypatch.setattr(
        "jupyter_tikz.magic.render_svg_with_artifacts", fake_render_svg_with_artifacts
    )

    tikz_magic.tikz("--keep-temp outputs/tmp", r"\draw (0,0) -- (1,1);")

    assert captured["output_dir"] == (tmp_path / "outputs" / "tmp").resolve()


def test_toolchain_option_parses(tikz_magic_mock):
    tikz_magic_mock.tikz("--toolchain xelatex_pdf2svg -nc", "any code")
    assert tikz_magic_mock.args["toolchain"] == "xelatex_pdf2svg"


def test_diagnose_without_code_prints_report(tikz_magic, monkeypatch, capsys):
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
            }
        },
    )
    tikz_magic.tikz("--diagnose")
    out, err = capsys.readouterr()
    assert "toolchain diagnostics" in out
    assert "pdftex_pdftocairo: ok" in out
    assert err == ""


def test_diagnose_json_output(tikz_magic, monkeypatch, capsys):
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
            }
        },
    )
    tikz_magic.tikz("--diagnose --json")
    out, err = capsys.readouterr()
    assert '"toolchains"' in out
    assert '"pdftex_pdftocairo"' in out
    assert err == ""


def test_diagnose_json_output_short_j_flag(tikz_magic, monkeypatch, capsys):
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
            }
        },
    )
    tikz_magic.tikz("--diagnose -j")
    out, err = capsys.readouterr()
    assert '"toolchains"' in out
    assert err == ""


def test_json_requires_diagnose(tikz_magic, capsys):
    res = tikz_magic.tikz("--json", r"\draw (0,0) -- (1,1);")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "--json" in err
    assert "--diagnose" in err


def test_diagnose_with_unknown_toolchain_reports_error(tikz_magic, capsys):
    res = tikz_magic.tikz("--diagnose --toolchain nope")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "Unknown toolchain: nope" in err


def test_toolchain_option_routes_selected_toolchain_to_executor(
    tikz_magic, monkeypatch, tmp_path
):
    captured: dict[str, str] = {}

    class _Artifacts:
        def __init__(self, workdir: Path):
            self.tex_path = workdir / "dummy.tex"
            self.pdf_path = None
            self.svg_path = workdir / "dummy.svg"

        def read_svg(self, *, strip_xml_declaration=True):
            _ = strip_xml_declaration
            return "<svg viewBox='0 0 1 1'></svg>"

    def fake_render_svg_with_artifacts(
        tex_source, *, output_dir, toolchain_name, output_stem
    ):
        _ = tex_source, output_stem
        out = Path(output_dir)
        captured["toolchain_name"] = toolchain_name
        out.mkdir(parents=True, exist_ok=True)
        return _Artifacts(out)

    monkeypatch.setattr(
        "jupyter_tikz.magic.render_svg_with_artifacts", fake_render_svg_with_artifacts
    )
    tikz_magic.tikz("--toolchain xelatex_pdf2svg", r"\draw (0,0) -- (1,1);")
    assert captured["toolchain_name"] == "xelatex_pdf2svg"


def test_output_stem_routes_to_executor(tikz_magic, monkeypatch):
    captured: dict[str, str] = {}

    class _Artifacts:
        def __init__(self, workdir: Path):
            self.tex_path = workdir / "dummy.tex"
            self.pdf_path = None
            self.svg_path = workdir / "dummy.svg"

        def read_svg(self, *, strip_xml_declaration=True):
            _ = strip_xml_declaration
            return "<svg viewBox='0 0 1 1'></svg>"

    def fake_render_svg_with_artifacts(
        tex_source, *, output_dir, toolchain_name, output_stem
    ):
        _ = tex_source, output_dir, toolchain_name
        captured["output_stem"] = output_stem
        return _Artifacts(Path("."))

    monkeypatch.setattr(
        "jupyter_tikz.magic.render_svg_with_artifacts", fake_render_svg_with_artifacts
    )
    tikz_magic.tikz("--output-stem custom_stem", r"\draw (0,0) -- (1,1);")
    assert captured["output_stem"] == "custom_stem"


def test_invalid_toolchain_is_validated_in_render_path(tikz_magic, capsys):
    res = tikz_magic.tikz("--toolchain nope", r"\draw (0,0) -- (1,1);")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "Unknown toolchain: nope" in err


def test_output_stem_routes_to_legacy_run_latex(tikz_magic, monkeypatch):
    captured: dict[str, str] = {}

    def fake_run_latex(self, *args, **kwargs):
        _ = self, args
        captured["output_stem"] = kwargs.get("output_stem")
        return "dummy_image"

    monkeypatch.setattr("jupyter_tikz.models.TexDocument.run_latex", fake_run_latex)
    tikz_magic.tikz("--tex-args=-shell-escape --output-stem legacy_stem", "x")
    assert captured["output_stem"] == "legacy_stem"


def test_invalid_output_stem_is_rejected_in_magic(tikz_magic, capsys):
    res = tikz_magic.tikz("--output-stem ../bad", r"\draw (0,0) -- (1,1);")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "output_stem" in err


def test_invalid_keep_temp_dir_is_rejected_in_magic(tikz_magic, capsys):
    res = tikz_magic.tikz("--keep-temp ../bad", r"\draw (0,0) -- (1,1);")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "keep-temp directory" in err


def test_invalid_save_image_path_is_reported_in_magic(tikz_magic, monkeypatch, capsys):
    class _Artifacts:
        tex_path = Path("dummy.tex")
        pdf_path = None
        svg_path = Path("dummy.svg")

        def read_svg(self, *, strip_xml_declaration=True):
            _ = strip_xml_declaration
            return "<svg viewBox='0 0 1 1'></svg>"

    monkeypatch.setattr(
        "jupyter_tikz.magic.render_svg_with_artifacts",
        lambda *args, **kwargs: _Artifacts(),
    )
    res = tikz_magic.tikz("--save-image ../bad", r"\draw (0,0) -- (1,1);")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "save destination" in err


def test_invalid_save_tex_path_is_reported_in_magic(tikz_magic, monkeypatch, capsys):
    class _Artifacts:
        tex_path = Path("dummy.tex")
        pdf_path = None
        svg_path = Path("dummy.svg")

        def read_svg(self, *, strip_xml_declaration=True):
            _ = strip_xml_declaration
            return "<svg viewBox='0 0 1 1'></svg>"

    monkeypatch.setattr(
        "jupyter_tikz.magic.render_svg_with_artifacts",
        lambda *args, **kwargs: _Artifacts(),
    )
    res = tikz_magic.tikz("--save-tex ../bad", r"\draw (0,0) -- (1,1);")
    out, err = capsys.readouterr()
    assert res is None
    assert out == ""
    assert "save destination" in err


# =================== Test src content ===================
def test_src_is_cell_content(tikz_magic_mock):
    # Arrange
    code = "code"

    line = ""  # DUMMY LINE
    cell = code

    # Act
    tikz_magic_mock.tikz(line, cell)

    # Assert
    assert tikz_magic_mock.src == cell


def test_src_is_line_code__code_not_in_local_ns(tikz_magic_mock):
    """
    Code param is a string, not a variable
    """

    # Arrange
    code = "code"

    line = code
    local_ns = None

    # Act
    tikz_magic_mock.tikz(line, local_ns=local_ns)  # magic_line

    # Assert
    assert tikz_magic_mock.src == line


def test_src_is_line__code_is_in_in_local_ns(tikz_magic_mock):
    """
    Code param is a variable
    """

    # Arrange
    code = "code"
    line = "$code_var"
    local_ns = {"$code_var": code}

    # Act
    tikz_magic_mock.tikz(line, local_ns=local_ns)

    # Assert
    assert tikz_magic_mock.src == code


# =================== Raise errors ===================
@pytest.mark.parametrize(
    "args",
    [
        "-t=a,b,c",
        "-l=d,e,f",
        "-lp=g,h,i",
        "-t=a,b,c -l=d,e,f",
        "-t=a,b,c -l=d,e,f -lp=g,h,i",
    ],
)
def test_raise_error_tex_preamble_and_extras_not_allowed_at_same_time(
    tikz_magic_mock, capsys, args
):
    # Arrange
    line = f"-preamble=any_preamble {args}"
    cell = "any cell content"

    # Act
    tikz_magic_mock.tikz(line, cell)

    # Assert
    _, err = capsys.readouterr()
    assert _EXTRAS_CONFLITS_ERR + "\n" == err


def test_raise_error_jinja_and_tex_prints_not_allowed_at_same_time(
    tikz_magic_mock, capsys
):
    # Arrange
    line = "-pj -pt"
    cell = "any cell content"

    # Act
    res = tikz_magic_mock.tikz(line, cell)

    # Assert
    _, err = capsys.readouterr()
    assert _PRINT_CONFLICT_ERR + "\n" == err
    assert res is None


@pytest.mark.parametrize(
    "args, expected_err",
    [
        ("-i -f", _INPUT_TYPE_CONFLIT_ERR),
        ("-i -as=f", _INPUT_TYPE_CONFLIT_ERR),
        ("-f -as=t", _INPUT_TYPE_CONFLIT_ERR),
        ("-i -f -as=s", _INPUT_TYPE_CONFLIT_ERR),
    ],
)
def test_raise_deprecated_args(tikz_magic_mock, capsys, args, expected_err):
    # Arrange
    line = args
    cell = "any cell content"

    # Act
    res = tikz_magic_mock.tikz(line, cell)

    # Assert
    _, err = capsys.readouterr()
    assert f"{expected_err}\n" == err
    assert res is None
