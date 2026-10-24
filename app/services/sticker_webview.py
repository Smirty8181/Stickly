from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from multiprocessing.connection import Client
from pathlib import Path
from threading import Lock
from uuid import uuid4

from app.paths import database_path

logger = logging.getLogger(__name__)


class WebStickerHost:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Окна стикеров WebView2 доступны только в Windows")
        self.address = rf"\\.\pipe\Stickly.Stickers.{uuid4().hex}"
        self.authkey = os.urandom(32)
        self._lock = Lock()
        self._closed = False
        command = [sys.executable, "--sticker-host", self.address, self.authkey.hex()]
        if not getattr(sys, "frozen", False):
            project_root = Path(__file__).resolve().parents[2]
            command = [
                sys.executable,
                str(project_root / "main.py"),
                "--sticker-host",
                self.address,
                self.authkey.hex(),
            ]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            command,
            cwd=str(Path(database_path()).parent),
            creationflags=creation_flags,
            close_fds=True,
        )
        try:
            self._request("ping", timeout=20)
        except (OSError, RuntimeError, TimeoutError):
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.error("Процесс окон стикеров не завершился после остановки")
            raise
        logger.info("Запущен процесс окон стикеров WebView2")

    def _request(self, action: str, *, timeout: float = 8, **values):
        if self._closed and action != "quit":
            raise RuntimeError("Процесс окон стикеров уже остановлен")
        deadline = time.monotonic() + timeout
        with self._lock:
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "Процесс стикеров завершился с кодом "
                        f"{self.process.returncode}"
                    )
                try:
                    connection = Client(
                        self.address, family="AF_PIPE", authkey=self.authkey
                    )
                    break
                except (OSError, EOFError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Не удалось связаться с процессом окон стикеров"
                        )
                    time.sleep(0.05)
            with connection:
                connection.send({"action": action, **values})
                if not connection.poll(max(0.1, deadline - time.monotonic())):
                    raise TimeoutError(
                        f"Процесс окон стикеров не ответил на команду {action}"
                    )
                response = connection.recv()
            if not isinstance(response, dict) or not response.get("ok"):
                detail = response.get("error", "Неизвестная ошибка") if isinstance(
                    response, dict
                ) else "Некорректный ответ процесса"
                raise RuntimeError(detail)
            return response.get("result")

    def open(self, note_id: str):
        return self._request("open", note_id=note_id)

    def show_all(self, note_ids: list[str]):
        return self._request("show_all", note_ids=note_ids)

    def hide_all(self):
        return self._request("hide_all")

    def hide(self, note_id: str):
        return self._request("hide", note_id=note_id)

    def save_all(self):
        return self._request("save_all")

    def show_main(self):
        return self._request("main_show")

    def hide_main(self):
        return self._request("main_hide")

    def refresh_main(self):
        return self._request("main_refresh")

    def show_settings(self):
        return self._request("main_settings")

    def quit(self):
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                connection = Client(
                    self.address, family="AF_PIPE", authkey=self.authkey
                )
                with connection:
                    connection.send({"action": "quit"})
                    if connection.poll(5):
                        connection.recv()
        except (OSError, EOFError, TimeoutError):
            logger.exception("Не удалось корректно закрыть процесс стикеров")
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            logger.error("Процесс окон стикеров не завершился вовремя")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.error("Не удалось завершить процесс окон стикеров")
