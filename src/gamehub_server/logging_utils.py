from __future__ import annotations

import logging


def get_server_logger(name: str) -> logging.Logger:
    return logging.getLogger("uvicorn.error").getChild(name)
