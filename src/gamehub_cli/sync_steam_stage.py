from __future__ import annotations

import sys as _sys

from .sync.steam_stage import *  # noqa: F401,F403
from .sync.steam_stage import __name__ as _target_name

_impl = _sys.modules[_target_name]
_sys.modules[__name__] = _impl
