from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
REGISTRY_VALUE = "Stickly"


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, REGISTRY_VALUE)
            executable = value.split('"', 2)[1] if value.startswith('"') else value.split()[0]
            return Path(executable).exists()
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("Не удалось прочитать настройку автозапуска")
        raise


def set_enabled(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Автозапуск поддерживается только в Windows")
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
    ) as key:
        if not enabled:
            try:
                winreg.DeleteValue(key, REGISTRY_VALUE)
            except FileNotFoundError:
                pass
            return

        if getattr(sys, "frozen", False):
            command = [sys.executable, "--minimized"]
        else:
            python = Path(sys.executable)
            pythonw = python.with_name("pythonw.exe")
            executable = pythonw if pythonw.exists() else python
            main_file = Path(sys.argv[0]).resolve()
            command = [str(executable), str(main_file), "--minimized"]
        winreg.SetValueEx(
            key,
            REGISTRY_VALUE,
            0,
            winreg.REG_SZ,
            subprocess.list2cmdline(command),
        )
    logger.info("Автозапуск %s", "включён" if enabled else "выключен")
