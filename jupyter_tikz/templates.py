from __future__ import annotations

import os

import jinja2


def render_jinja(tex_obj, ns) -> None:
    """Render a historical TexDocument template with its namespace."""

    fs_loader = jinja2.FileSystemLoader(os.getcwd())

    tmpl_env = jinja2.Environment(
        loader=fs_loader,
        block_start_string="(**",
        block_end_string="**)",
        variable_start_string="(*",
        variable_end_string="*)",
        comment_start_string="(~",
        comment_end_string="~)",
    )

    tmpl = tmpl_env.from_string(tex_obj._code)
    tex_obj._code = tmpl.render(**ns)
