"""Load a test file that isn't part of a package (no __init__.py) as an isolated module.

Used by the unit tests that check the wiring inside tests/integration/test_t5_frontend_e2e.py
without actually letting it run a real subprocess.
"""

import importlib.util
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(relative_path: str, module_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
