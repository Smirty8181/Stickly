from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.paths import log_path


def configure_logging() -> None:
    handler = RotatingFileHandler(
        log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])
