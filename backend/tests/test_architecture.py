"""Architecture rules as a test: running `pytest` also checks module boundaries.

The contracts live in pyproject.toml ([tool.importlinter]):
- app.core never imports business modules;
- business modules use each other only through their public api.py.
"""

import os
from pathlib import Path

from importlinter.cli import lint_imports

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_module_boundaries_hold() -> None:
    cwd = Path.cwd()
    os.chdir(BACKEND_DIR)  # import-linter reads pyproject.toml from the working directory
    try:
        exit_code = lint_imports(no_cache=True)
    finally:
        os.chdir(cwd)
    assert exit_code == 0, "Module boundaries broken - run `lint-imports` for details."
