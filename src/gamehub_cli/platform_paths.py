from __future__ import annotations

import sys as _sys

from .common.platform_paths import *  # noqa: F401,F403
from .common.platform_paths import __name__ as _target_name

_impl = _sys.modules[_target_name]
_sys.modules[__name__] = _impl
