from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "server"))
sys.path.insert(0, str(ROOT / "apps" / "cli"))
sys.path.insert(0, str(ROOT / "shared" / "gamehub_common"))
