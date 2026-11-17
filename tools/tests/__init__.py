"""Tests for the build tools in tools/ (build machine only). Run from the repository root with the build venv:
  derived/buildenv/bin/python -B -m unittest discover -s tools/tests -t .
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / 'tools'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
