{% include "templates/notebook-download.md" %}

## Troubleshooting toolchain PATH issues

The default magic execution path depends on these command-line tools:
- `latexmk`
- `pdftocairo` (or the binary configured by `JUPYTER_TIKZ_PDFTOCAIROPATH`)

If one of them is not accessible, errors may look like:

<div class="result" style="padding-right: 0;">
<div class="log-output">
latexmk: command not found
<br>
pdftocairo: No such file or directory
</div>
</div>

First, ensure these commands are available in the same environment used by your notebook kernel:

```shell
latexmk -v
pdftocairo -v
```

You can also run built-in diagnostics from a notebook to inspect toolchain
resolution and discovered executable paths:

```python
%tikz --diagnose
```

JSON output:

```python
%tikz --diagnose --json
```

`--json` must be used with `--diagnose`; `%tikz --json` alone is rejected.

To diagnose one specific toolchain:

```python
%tikz --diagnose --toolchain=xelatex_pdftocairo
```

If `pdftocairo` is installed but not in `PATH`, configure it explicitly:

```python
import os
os.environ["JUPYTER_TIKZ_PDFTOCAIROPATH"] = r"C:\path\to\pdftocairo.exe"
```

## Troubleshooting `pdflatex` path with custom `-tp`

When you explicitly set `-tp=<tex_program>` to a full executable path (or use a TeX program outside the default toolchain mapping), that executable must also be reachable.

```python
# Replace with your local executable path
PDF_LATEX_PATH = r"C:\Users\lucas\AppData\Local\Programs\MiKTeX\miktex\bin\x64\pdflatex.exe"
```

```latex
%%tikz -as=tikz -t=pgfplots -nt -tp="$PDF_LATEX_PATH"
\begin{axis}[
  xlabel=$x$,
  ylabel={$f(x) = x^2 - x + 4$}
]
\addplot {x^2 - x + 4};
\end{axis}
```

<div class="result" markdown>
![Another quadratic formula](../assets/tikz/another_quadratic.svg)
</div>
