"""Evaluation suite for FrontierSQL (Milestone 11). See EVALUATION_PLAN.md.

Run from the repository root, e.g. `python -m evaluation.run --help`. The backend package
(`app`) is imported from backend/, which is put on the import path here.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "evaluation"
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
