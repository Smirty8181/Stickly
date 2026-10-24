from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Stickly"


def data_directory() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(relative_path: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / relative_path


def database_path() -> Path:
    return data_directory() / "stickly.sqlite3"


def log_path() -> Path:
    return data_directory() / "stickly.log"
