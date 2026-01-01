import shutil
import subprocess
from pathlib import Path


def crop_svg_inplace(svg_path: Path) -> bool:
    """
    Crop an SVG to its drawing area using Inkscape.
    Modifies the file in place.
    Returns True if cropping was performed, False otherwise.
    """
    if shutil.which("inkscape") is None:
        return False

    # Inkscape ≥1.0 CLI
    cmd = [
        "inkscape",
        str(svg_path),
        "--export-area-drawing",
        "--export-filename",
        str(svg_path),
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return proc.returncode == 0

