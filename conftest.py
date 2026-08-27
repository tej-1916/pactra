"""Ensure the repository root is importable so packages/, services/, apps/
resolve as top-level packages during tests."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
