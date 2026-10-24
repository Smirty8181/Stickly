from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter

logger = logging.getLogger(__name__)


class GlobalHotkeys(QAbstractNativeEventFilter):
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    def __init__(
        self,
        create_note: Callable[[], None],
        show_main: Callable[[], None],
        toggle_notes: Callable[[], None],
    ):
        super().__init__()
        self._callbacks = {
            1: create_note,
            2: show_main,
            3: toggle_notes,
        }
        self._registered: list[int] = []

    def enable(self) -> None:
        if os.name != "nt":
            raise OSError("Глобальные сочетания доступны только в Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.RegisterHotKey.argtypes = (
            wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT
        )
        user32.RegisterHotKey.restype = wintypes.BOOL
        for hotkey_id, virtual_key in ((1, 0x4E), (2, 0x48), (3, 0x53)):
            ctypes.set_last_error(0)
            registered = user32.RegisterHotKey(
                None,
                hotkey_id,
                self.MOD_ALT | self.MOD_CONTROL | self.MOD_NOREPEAT,
                virtual_key,
            )
            if not registered:
                self.disable()
                error = ctypes.get_last_error()
                raise OSError(
                    error,
                    f"Не удалось зарегистрировать Alt+Ctrl+{chr(virtual_key)}. "
                    "Возможно, сочетание уже используется другой программой.",
                )
            self._registered.append(hotkey_id)
        logger.info("Зарегистрированы глобальные сочетания клавиш")

    def disable(self) -> None:
        if os.name == "nt":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.UnregisterHotKey.argtypes = (wintypes.HWND, wintypes.INT)
            user32.UnregisterHotKey.restype = wintypes.BOOL
            for hotkey_id in self._registered:
                user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()

    def nativeEventFilter(self, event_type, message):
        if os.name != "nt" or event_type != b"windows_generic_MSG":
            return False, 0
        msg = ctypes.cast(message, ctypes.POINTER(wintypes.MSG)).contents
        if msg.message == self.WM_HOTKEY and msg.wParam in self._callbacks:
            self._callbacks[msg.wParam]()
            return True, 0
        return False, 0
