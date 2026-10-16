"""Build disposable synthetic fixtures instead of depending on local outputs."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from scripts.generate_fake_data import generate


def make_stress_data(folder: Path) -> Path:
    with contextlib.redirect_stdout(io.StringIO()):
        generate(folder, 75, 42)
    return folder
