"""Test bootstrap: put harness/scripts on sys.path for flat imports.

The harness lives at <project>/harness with sources in scripts/ and tests in
tests/. ``python -m unittest discover -s tests`` adds tests/ (not scripts/) to
sys.path, so the test files' flat imports (e.g. ``from profile import ...``)
would otherwise resolve to unrelated stdlib modules. Import this module first
in each test file to insert scripts/ onto sys.path.
"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
