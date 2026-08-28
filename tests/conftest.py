"""Put the pure engine on the import path. Tests need no database and no network."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "engine" / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)
