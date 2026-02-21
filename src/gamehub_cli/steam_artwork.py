from __future__ import annotations

import sys as _sys

from .steam.artwork import *  # noqa: F401,F403
from .steam.artwork import __name__ as _target_name

_impl = _sys.modules[_target_name]
_sys.modules[__name__] = _impl
