from __future__ import annotations

import sys as _sys

from .emulators.installer import *  # noqa: F401,F403
from .emulators.installer import __name__ as _target_name

_impl = _sys.modules[_target_name]
_sys.modules[__name__] = _impl
