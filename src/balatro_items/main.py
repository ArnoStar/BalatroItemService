"""``uvicorn balatro_items.main:app`` (or the ``balatro-items`` command).
Settings come from BALATRO_ITEMS_* environment variables (see config.py)."""

from __future__ import annotations

import logging
import os

from .bootstrap import build_use_cases
from .config import Settings
from .presentation.http import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = Settings.from_env()
app = create_app(build_use_cases(settings), settings.cors_origins)


def run() -> None:
    import uvicorn

    uvicorn.run("balatro_items.main:app", host=os.environ.get("BALATRO_ITEMS_HOST", "127.0.0.1"),
                port=int(os.environ.get("BALATRO_ITEMS_PORT", "8004")))
