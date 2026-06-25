"""Import shim for the project when the checkout folder has a display name.

The source folders live at the repository root. This package exposes them under
the stable ``commodity_etf_dashboard`` import path used by tests and scripts.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
__path__ = [str(_PROJECT_ROOT)]

__version__ = "0.1.0"
