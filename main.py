from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sqlite3
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QByteArray, QEventLoop, QTimer, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from app.database import Database
from app.logging_config import configure_logging
from app.paths import database_path, resource_path
from app.services.hotkey_service import GlobalHotkeys
from app.services.startup_service import is_enabled, set_enabled
from app.services.sticker_webview import WebStickerHost

logger = logging.getLogger("stickly")
SERVER_NAME = "Stickly.Desktop.Notes.v1"


def parse_arguments():
    parser = argparse.ArgumentParser(description="Stickly — заметки и задачи")
    parser.add_argument("--minimized", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--create", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sticker-host",
        nargs=2,
        metavar=("PIPE", "AUTH"),
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def claim_single_instance(
    command: str,
) -> tuple[bool, QLocalServer | None, int | None]:
    server = QLocalServer()
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        )
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        mutex_name = f"Local\\{SERVER_NAME}"
        ctypes.set_last_error(0)
        mutex = kernel32.CreateMutexW(
            None, True, mutex_name
        )
        if not mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        mutex_handle = int(mutex)
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(mutex)
            if _forward_command(command):
                return False, None, None
            raise RuntimeError(
                "Stickly уже запущен, но не подтвердил команду. "
                "Подождите несколько секунд и повторите запуск."
            )
        QLocalServer.removeServer(SERVER_NAME)
        if not server.listen(SERVER_NAME):
            kernel32.CloseHandle(mutex)
            raise RuntimeError(
                "Не удалось открыть канал управления Stickly: "
                f"{server.errorString()}"
            )
        return True, server, mutex_handle

    if server.listen(SERVER_NAME):
        return True, server, None
    if _forward_command(command):
        return False, None, None
    raise RuntimeError("Не удалось связаться с уже запущенным Stickly.")


def _forward_command(command: str) -> bool:
    socket = QLocalSocket()
    loop = QEventLoop()
    retry_timer = QTimer()
    retry_timer.setSingleShot(True)
    retry_timer.setInterval(100)
    timeout_timer = QTimer()
    timeout_timer.setSingleShot(True)
    timeout_timer.setInterval(5000)
    state = {"sent": False, "acknowledged": False, "response": bytearray()}

    def connect():
        if state["sent"] or state["acknowledged"]:
            return
        socket.abort()
        socket.connectToServer(SERVER_NAME)

    def send():
        if state["sent"]:
            return
        state["sent"] = True
        retry_timer.stop()
        payload = QByteArray(f"{command}\n".encode("utf-8"))
        if socket.write(payload) != len(payload):
            loop.quit()
            return
        socket.flush()

    def receive():
        state["response"].extend(bytes(socket.readAll()))
        if state["response"].endswith(b"ok"):
            state["acknowledged"] = True
            loop.quit()

    def socket_error(_error):
        if state["sent"]:
            loop.quit()
        elif not retry_timer.isActive():
            retry_timer.start()

    socket.connected.connect(send)
    socket.readyRead.connect(receive)
    socket.errorOccurred.connect(socket_error)
    retry_timer.timeout.connect(connect)
    timeout_timer.timeout.connect(loop.quit)
    timeout_timer.start()
    connect()
    loop.exec()
    retry_timer.stop()
    timeout_timer.stop()
    socket.abort()
    return state["acknowledged"]


class SticklyApplication:
    def __init__(
        self,
        app: QApplication,
        server: QLocalServer,
        minimized: bool,
        instance_lock: int | None,
    ):
        self.app = app
        self.server = server
        self.instance_lock = instance_lock
        self.database = Database(database_path())
        self.sticker_host = WebStickerHost()
        self.settings = self.database.get_settings()
        if os.name == "nt":
            try:
                startup_enabled = is_enabled()
                if startup_enabled != self.settings["start_with_windows"]:
                    self.settings = self.database.set_settings(
                        start_with_windows=startup_enabled
                    )
            except OSError:
                logger.exception("Не удалось определить состояние автозапуска")
        self.stickers: set[str] = set()
        self._refresh_timer = QTimer(self.app)
        self._refresh_timer.setInterval(1500)
        self._refresh_timer.timeout.connect(self._refresh_if_data_changed)
        self._refresh_signature = self._data_signature()
        self._refresh_timer.start()
        self.server.newConnection.connect(self._handle_connection)
        self._build_tray()
        self.hotkeys: GlobalHotkeys | None = None
        if self.settings["global_hotkeys"]:
            try:
                self._enable_hotkeys()
            except OSError:
                logger.exception("Не удалось включить глобальные сочетания")
                self.settings = self.database.set_settings(global_hotkeys=False)
                QMessageBox.warning(
                    None,
                    "Глобальные сочетания недоступны",
                    "Одно из сочетаний клавиш уже используется другой программой. "
                    "Откройте настройки Stickly, чтобы выбрать другой режим.",
                )
        self._restore_stickers()
        if not minimized:
            self.show_main()
        logger.info("Stickly запущен")

    def _build_tray(self):
        self.tray = QSystemTrayIcon(
            QIcon(resource_path("assets/stickly-logo.ico").as_posix()), self.app
        )
        self.tray.setToolTip("Stickly — заметки и задачи")
        menu = QMenu()
        self._add_menu_action(menu, "Создать стикер", self.create_note)
        self._add_menu_action(menu, "Показать все стикеры", self.show_all_stickers)
        self._add_menu_action(menu, "Скрыть все стикеры", self.hide_all_stickers)
        menu.addSeparator()
        self._add_menu_action(menu, "Открыть Stickly", self.show_main)
        self._add_menu_action(menu, "Настройки", self.open_settings)
        menu.addSeparator()
        self._add_menu_action(menu, "Выход", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            logger.warning("Системный трей недоступен в текущем окружении")

    @staticmethod
    def _add_menu_action(menu: QMenu, title: str, callback):
        action = QAction(title, menu)
        action.triggered.connect(callback)
        menu.addAction(action)

    def _tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_main()

    def _handle_connection(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(
                lambda current=socket: self._process_command(current)
            )
            if socket.bytesAvailable():
                self._process_command(socket)

    def _process_command(self, socket: QLocalSocket):
        if socket.property("command_processed"):
            return
        buffer = bytes(socket.property("command_buffer") or b"")
        buffer += bytes(socket.readAll())
        if not buffer.endswith(b"\n"):
            socket.setProperty("command_buffer", QByteArray(buffer))
            return
        command = buffer.decode("utf-8", "replace").strip()
        if not command:
            return
        socket.setProperty("command_processed", True)
        if command == "create":
            self.create_note()
        elif command == "quit":
            self.quit()
        else:
            self.show_main()
        socket.write(QByteArray(b"ok"))
        socket.flush()
        socket.disconnectFromServer()

    def show_main(self):
        try:
            self.sticker_host.show_main()
        except (OSError, RuntimeError, TimeoutError):
            logger.exception("Не удалось открыть главную панель")
            QMessageBox.warning(
                None,
                "Главная панель",
                "Не удалось открыть Stickly. Проверьте установку WebView2 Runtime.",
            )

    def create_note(self):
        try:
            note = self.database.create_note(
                color=self.settings["default_color"],
                width=self.settings["default_width"],
                height=self.settings["default_height"],
                font_size=self.settings["default_font_size"],
            )
            self.open_note(note["id"])
        except (OSError, ValueError, sqlite3.Error):
            logger.exception("Не удалось создать заметку")
            QMessageBox.critical(None, "Ошибка", "Не удалось создать стикер.")

    def open_note(self, note_id: str):
        note = self.database.get_note(note_id)
        if not note or note["deleted_at"] or note["is_archived"]:
            if note and note["is_archived"]:
                self.database.update_note(note_id, is_archived=0, is_visible=1)
                note = self.database.get_note(note_id)
            else:
                return
        if note_id in self.stickers:
            try:
                self.sticker_host.open(note_id)
            except (OSError, RuntimeError, TimeoutError):
                logger.exception("Не удалось повторно открыть стикер %s", note_id)
                QMessageBox.warning(
                    None,
                    "Окно заметки",
                    "Не удалось открыть стикер. Проверьте, установлен ли WebView2 Runtime.",
                )
            return
        if self._normalize_position(note):
            self.database.update_note(
                note_id,
                x=note["x"],
                y=note["y"],
                width=note["width"],
                height=note["height"],
            )
        try:
            self.sticker_host.open(note_id)
        except (OSError, RuntimeError, TimeoutError):
            logger.exception("Не удалось открыть стикер %s", note_id)
            QMessageBox.warning(
                None,
                "Окно заметки",
                "Не удалось открыть стикер. Проверьте, установлен ли WebView2 Runtime.",
            )
            return
        self.stickers.add(note_id)

    def _data_signature(self):
        notes = self.database.list_notes()
        note_state = tuple(
            (
                note["id"],
                note["title"],
                note["body"],
                note["color"],
                note["custom_color"],
                note["is_archived"],
                note["is_visible"],
                note["updated_at"],
                tuple(
                    (task["id"], task["text"], task["completed"], task["position"])
                    for task in note["tasks"]
                ),
            )
            for note in notes
        )
        trash_state = tuple(
            (note["id"], note["title"], note["deleted_at"])
            for note in self.database.list_trash()
        )
        return note_state, trash_state

    def _refresh_if_data_changed(self):
        if self.database.consume_runtime_value("quit_requested") == "1":
            self.quit()
            return
        self._sync_external_settings()
        signature = self._data_signature()
        if signature != self._refresh_signature:
            self._refresh_signature = signature
            try:
                self.sticker_host.refresh_main()
            except (OSError, RuntimeError, TimeoutError):
                logger.exception("Не удалось обновить главную панель")

    def _sync_external_settings(self):
        values = self.database.get_settings()
        if values == self.settings:
            return
        corrected = values.copy()
        if values["start_with_windows"] != self.settings["start_with_windows"]:
            try:
                set_enabled(values["start_with_windows"])
            except OSError:
                logger.exception("Не удалось применить автозапуск из настроек")
                corrected["start_with_windows"] = self.settings["start_with_windows"]
                QMessageBox.warning(
                    None,
                    "Автозапуск",
                    "Не удалось изменить автозапуск Windows. "
                    "Сохранено предыдущее значение.",
                )
        if values["global_hotkeys"] != self.settings["global_hotkeys"]:
            try:
                if values["global_hotkeys"]:
                    self._enable_hotkeys()
                else:
                    self._disable_hotkeys()
            except OSError as error:
                logger.exception("Не удалось применить горячие клавиши из настроек")
                corrected["global_hotkeys"] = self.settings["global_hotkeys"]
                QMessageBox.warning(None, "Горячие клавиши", str(error))
        if corrected != values:
            corrected = self.database.set_settings(**corrected)
        self.settings = corrected

    @staticmethod
    def _normalize_position(note: dict) -> bool:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QRect

        target = QRect(note["x"], note["y"], note["width"], note["height"])
        geometries = [screen.availableGeometry() for screen in QGuiApplication.screens()]
        if any(area.contains(target) for area in geometries):
            return False
        screen = max(
            QGuiApplication.screens(),
            key=lambda item: item.availableGeometry().intersected(target).width()
            * item.availableGeometry().intersected(target).height(),
            default=QGuiApplication.primaryScreen(),
        )
        if screen is None:
            return False
        area = screen.availableGeometry()
        previous = (note["x"], note["y"], note["width"], note["height"])
        note["width"] = min(note["width"], area.width())
        note["height"] = min(note["height"], area.height())
        note["x"] = max(area.left(), min(note["x"], area.right() - note["width"] + 1))
        note["y"] = max(area.top(), min(note["y"], area.bottom() - note["height"] + 1))
        return previous != (note["x"], note["y"], note["width"], note["height"])

    def _restore_stickers(self):
        for note in self.database.list_notes(status="active"):
            if note["is_visible"]:
                try:
                    self.open_note(note["id"])
                except (
                    OSError,
                    RuntimeError,
                    TimeoutError,
                    ValueError,
                    KeyError,
                    sqlite3.Error,
                ):
                    logger.exception("Не удалось восстановить стикер %s", note["id"])

    def show_all_stickers(self):
        notes = self.database.list_notes(status="active")
        self.sticker_host.show_all([note["id"] for note in notes])
        for note in notes:
            self.database.update_note(note["id"], is_visible=1)
            self.stickers.add(note["id"])

    def hide_all_stickers(self):
        self.sticker_host.hide_all()
        for note in self.database.list_notes(status="active"):
            self.database.update_note(note["id"], is_visible=0)

    def open_settings(self):
        try:
            self.sticker_host.show_settings()
        except (OSError, RuntimeError, TimeoutError):
            logger.exception("Не удалось открыть настройки")
            QMessageBox.warning(
                None, "Настройки", "Не удалось открыть настройки Stickly."
            )

    def _enable_hotkeys(self):
        if self.hotkeys:
            return
        hotkeys = GlobalHotkeys(
            self.create_note, self.show_main, self.toggle_all_stickers
        )
        self.app.installNativeEventFilter(hotkeys)
        try:
            hotkeys.enable()
        except OSError:
            self.app.removeNativeEventFilter(hotkeys)
            raise
        self.hotkeys = hotkeys

    def _disable_hotkeys(self):
        if self.hotkeys:
            self.hotkeys.disable()
            self.app.removeNativeEventFilter(self.hotkeys)
            self.hotkeys = None

    def toggle_all_stickers(self):
        if any(note["is_visible"] for note in self.database.list_notes(status="active")):
            self.hide_all_stickers()
        else:
            self.show_all_stickers()

    def save_all(self):
        try:
            self.sticker_host.save_all()
        except (OSError, RuntimeError, TimeoutError):
            logger.exception("Не удалось сохранить стикеры")
            QMessageBox.warning(
                None,
                "Сохранение",
                "Не удалось сохранить положение одного или нескольких стикеров.",
            )
            return
        self.tray.showMessage("Stickly", "Все заметки сохранены")

    def quit(self):
        logger.info("Завершение работы Stickly")
        try:
            self.sticker_host.save_all()
        except (OSError, RuntimeError, TimeoutError):
            logger.exception("Не удалось сохранить стикеры перед выходом")
        try:
            self.sticker_host.quit()
        except (OSError, RuntimeError, TimeoutError):
            logger.exception("Не удалось корректно закрыть окна стикеров")
        self._disable_hotkeys()
        self.tray.hide()
        self.server.close()
        QLocalServer.removeServer(SERVER_NAME)
        self.database.close()
        if self.instance_lock:
            _release_instance_lock(self.instance_lock)
            self.instance_lock = None
        self.app.quit()


def main() -> int:
    configure_logging()
    args = parse_arguments()
    if args.sticker_host:
        try:
            from app.services.web_sticker_host import run_webview_host

            pipe, auth = args.sticker_host
            return run_webview_host(pipe, bytes.fromhex(auth), str(database_path()))
        except (OSError, RuntimeError, ValueError):
            logger.exception("Не удалось запустить окна стикеров WebView2")
            return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Stickly")
    app.setOrganizationName("Stickly")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    style_file = resource_path("app/ui/styles.qss")
    if style_file.exists():
        app.setStyleSheet(style_file.read_text(encoding="utf-8"))
    icon_file = resource_path("assets/stickly-logo.ico")
    if icon_file.exists():
        app.setWindowIcon(QIcon(icon_file.as_posix()))

    instance_lock = None
    server = None
    try:
        is_primary, server, instance_lock = claim_single_instance(
            "create" if args.create else "show"
        )
        if not is_primary:
            return 0
        instance = SticklyApplication(app, server, args.minimized, instance_lock)
        if args.create:
            instance.create_note()
    except (OSError, RuntimeError, ValueError, sqlite3.Error):
        logger.exception("Не удалось запустить приложение")
        if server:
            server.close()
        if instance_lock and os.name == "nt":
            _release_instance_lock(instance_lock)
        QMessageBox.critical(
            None,
            "Stickly не запустился",
            "Не удалось запустить приложение или открыть хранилище заметок. "
            f"Подробности записаны в журнал:\n{Path(database_path()).parent / 'stickly.log'}",
        )
        return 1
    app.aboutToQuit.connect(instance.database.close)
    return app.exec()


def _release_instance_lock(handle: int) -> None:
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    mutex = wintypes.HANDLE(handle)
    if not kernel32.ReleaseMutex(mutex):
        logger.warning("Windows не подтвердила освобождение mutex Stickly")
    if not kernel32.CloseHandle(mutex):
        logger.warning("Windows не смогла закрыть mutex Stickly")


if __name__ == "__main__":
    raise SystemExit(main())
