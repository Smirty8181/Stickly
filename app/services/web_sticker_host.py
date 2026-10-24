from __future__ import annotations

import logging
import sqlite3
from multiprocessing.connection import Listener
from threading import Lock, Thread, Timer
from typing import Any

import webview
from webview.errors import JavascriptException

from app.database import Database
from app.paths import resource_path

logger = logging.getLogger(__name__)


class StickerApi:
    def __init__(self, database_file: str, note_id: str, window, host):
        self._database_file = database_file
        self._note_id = note_id
        self._window = window
        self._host = host
        self._position_lock = Lock()
        self._geometry_timer: Timer | None = None

    def _database(self) -> Database:
        return Database(self._database_file)

    def get_note_data(self) -> dict[str, Any]:
        database = self._database()
        try:
            note = database.get_note(self._note_id)
            if not note or note["deleted_at"]:
                raise KeyError("Заметка была удалена")
            note["tasks"] = database.list_tasks(self._note_id)
            note["autosave_delay"] = database.get_settings()["autosave_delay"]
            return note
        finally:
            database.close()

    def save_content(
        self, note_id: str, title: str, body: str, font_size: int
    ) -> bool:
        self._check_note(note_id)
        database = self._database()
        try:
            database.update_note(
                note_id,
                title=str(title)[:500],
                body=str(body)[:1_000_000],
                font_size=max(9, min(32, int(font_size))),
            )
            return True
        finally:
            database.close()

    def set_color(
        self, note_id: str, color: str, custom_color: str = ""
    ) -> bool:
        self._check_note(note_id)
        allowed = {
            "yellow", "pink", "mint", "blue", "lavender", "peach",
            "gray", "graphite", "dark", "cream", "custom",
        }
        if not isinstance(color, str) or color not in allowed:
            raise ValueError("Неизвестная тема бумаги")
        if color == "custom" and not (
            isinstance(custom_color, str)
            and len(custom_color) == 7
            and custom_color.startswith("#")
            and all(
                character in "0123456789abcdefABCDEF"
                for character in custom_color[1:]
            )
        ):
            raise ValueError("Некорректный пользовательский цвет")
        database = self._database()
        try:
            database.update_note(
                note_id,
                color=color,
                **({"custom_color": custom_color} if color == "custom" else {}),
            )
            return True
        finally:
            database.close()

    def set_pin(self, note_id: str, enabled: bool) -> bool:
        self._check_note(note_id)
        database = self._database()
        try:
            database.update_note(note_id, always_on_top=int(bool(enabled)))
        finally:
            database.close()
        self._window.on_top = bool(enabled)
        return True

    def hide_sticker(self, note_id: str) -> bool:
        self._check_note(note_id)
        self.save_geometry()
        database = self._database()
        try:
            database.update_note(note_id, is_visible=0)
        finally:
            database.close()
        self._window.hide()
        return True

    def move_window(self, dx: int, dy: int) -> bool:
        x = max(-32000, min(32000, int(self._window.x) + int(dx)))
        y = max(-32000, min(32000, int(self._window.y) + int(dy)))
        self._window.move(x, y)
        self._schedule_geometry_save()
        return True

    def resize_window(self, dx: int, dy: int) -> bool:
        width = max(300, min(1024, int(self._window.width) + int(dx)))
        height = max(290, min(1200, int(self._window.height) + int(dy)))
        self._window.resize(width, height)
        self._schedule_geometry_save()
        return True

    def save_geometry(self) -> bool:
        database = self._database()
        try:
            database.update_note(
                self._note_id,
                x=int(self._window.x),
                y=int(self._window.y),
                width=max(220, int(self._window.width) - 44),
                height=max(180, int(self._window.height) - 44),
            )
            return True
        finally:
            database.close()

    def save_now(self) -> bool:
        content = self._window.evaluate_js(
            "window.sticklyReadContent ? window.sticklyReadContent() : null"
        )
        if isinstance(content, dict):
            self.save_content(
                self._note_id,
                content.get("title", ""),
                content.get("body", ""),
                content.get("font_size", 14),
            )
        return self.save_geometry()

    def add_task(self, note_id: str, text: str) -> dict[str, Any]:
        self._check_note(note_id)
        database = self._database()
        try:
            return database.add_task(note_id, str(text)[:500])
        finally:
            database.close()

    def toggle_task(self, task_id: str, completed: bool) -> dict[str, Any]:
        database = self._database()
        try:
            task = database.get_task(task_id)
            if not task or task["note_id"] != self._note_id:
                raise KeyError("Задача не найдена")
            return database.update_task(task_id, completed=int(bool(completed)))
        finally:
            database.close()

    def delete_task(self, task_id: str) -> bool:
        database = self._database()
        try:
            task = database.get_task(task_id)
            if not task or task["note_id"] != self._note_id:
                raise KeyError("Задача не найдена")
            database.delete_task(task_id)
            return True
        finally:
            database.close()

    def reorder_tasks(self, note_id: str, ordered_ids: list[str]) -> bool:
        self._check_note(note_id)
        database = self._database()
        try:
            database.reorder_tasks(note_id, ordered_ids)
            return True
        finally:
            database.close()

    def duplicate_note(self, note_id: str) -> str:
        self._check_note(note_id)
        database = self._database()
        try:
            note = database.duplicate_note(note_id)
        finally:
            database.close()
        self._host.open_note(note["id"])
        return note["id"]

    def archive_note(self, note_id: str) -> bool:
        return self._close_note(note_id, archive=True)

    def trash_note(self, note_id: str) -> bool:
        return self._close_note(note_id, trash=True)

    def _close_note(self, note_id: str, *, archive=False, trash=False) -> bool:
        self._check_note(note_id)
        self.save_geometry()
        database = self._database()
        try:
            if trash:
                database.soft_delete_note(note_id)
            else:
                database.update_note(
                    note_id, is_archived=int(archive), is_visible=0
                )
        finally:
            database.close()
        self._window.hide()
        return True

    def _schedule_geometry_save(self):
        with self._position_lock:
            if self._geometry_timer:
                self._geometry_timer.cancel()
            self._geometry_timer = Timer(0.3, self._save_geometry_safely)
            self._geometry_timer.daemon = True
            self._geometry_timer.start()

    def _save_geometry_safely(self):
        try:
            self.save_geometry()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось сохранить геометрию стикера %s", self._note_id)

    def _check_note(self, note_id: str):
        if note_id != self._note_id:
            raise ValueError("Запрос относится к другому стикеру")


class DashboardApi:
    def __init__(self, database_file: str, host):
        self._database_file = database_file
        self._host = host
        self._window = None

    def _database(self) -> Database:
        return Database(self._database_file)

    def get_dashboard_data(
        self,
        query: str = "",
        status: str = "all",
        color: str = "all",
        sort: str = "updated",
        task_filter: str = "all",
    ) -> dict[str, Any]:
        if status not in {"all", "active", "archived"}:
            raise ValueError("Неизвестный раздел заметок")
        if color != "all" and color not in {
            "yellow", "pink", "mint", "blue", "lavender", "peach",
            "gray", "graphite", "cream", "dark", "custom",
        }:
            raise ValueError("Неизвестный фильтр цвета")
        if sort not in {"updated", "created"}:
            raise ValueError("Неизвестный порядок сортировки")
        if task_filter not in {"all", "active", "completed"}:
            raise ValueError("Неизвестный фильтр задач")
        database = self._database()
        try:
            notes = database.list_notes(
                query=str(query)[:500],
                status=status,
                color=color,
                sort=sort,
            )
            all_notes = database.list_notes()
            active_notes = database.list_notes(status="active")
            tasks = [
                {
                    **task,
                    "note_title": note["title"] or "Без заголовка",
                }
                for note in active_notes
                for task in note["tasks"]
                if (
                    task_filter == "all"
                    or (task_filter == "active" and not task["completed"])
                    or (task_filter == "completed" and task["completed"])
                )
            ]
            all_tasks = [task for note in active_notes for task in note["tasks"]]
            return {
                "notes": notes,
                "tasks": tasks,
                "trash": database.list_trash(),
                "stats": {
                    "notes": len(all_notes),
                    "active_tasks": sum(not task["completed"] for task in all_tasks),
                    "completed_tasks": sum(bool(task["completed"]) for task in all_tasks),
                    "filtered_notes": len(notes),
                    "remaining_tasks": sum(not task["completed"] for task in all_tasks),
                },
                "settings": database.get_settings(),
            }
        finally:
            database.close()

    def create_note(self) -> str:
        database = self._database()
        try:
            settings = database.get_settings()
            note = database.create_note(
                color=settings["default_color"],
                width=settings["default_width"],
                height=settings["default_height"],
                font_size=settings["default_font_size"],
            )
        finally:
            database.close()
        if not self._host.open_note(note["id"]):
            raise RuntimeError("Не удалось открыть новый стикер")
        return note["id"]

    def open_note(self, note_id: str) -> bool:
        database = self._database()
        try:
            note = database.get_note(str(note_id))
            if not note or note["deleted_at"]:
                raise KeyError("Заметка не найдена")
            if note["is_archived"]:
                database.update_note(note_id, is_archived=0)
        finally:
            database.close()
        if not self._host.open_note(note_id):
            raise RuntimeError("Не удалось открыть стикер")
        return True

    def duplicate_note(self, note_id: str) -> str:
        database = self._database()
        try:
            duplicate = database.duplicate_note(str(note_id))
        finally:
            database.close()
        if not self._host.open_note(duplicate["id"]):
            raise RuntimeError("Не удалось открыть копию стикера")
        return duplicate["id"]

    def archive_note(self, note_id: str) -> bool:
        self._host.hide(str(note_id))
        database = self._database()
        try:
            database.update_note(
                str(note_id), is_archived=1, is_visible=0
            )
        finally:
            database.close()
        return True

    def trash_note(self, note_id: str) -> bool:
        self._host.hide(str(note_id))
        database = self._database()
        try:
            database.soft_delete_note(str(note_id))
        finally:
            database.close()
        return True

    def restore_note(self, note_id: str) -> bool:
        database = self._database()
        try:
            database.restore_note(str(note_id))
        finally:
            database.close()
        return True

    def delete_note_permanently(self, note_id: str) -> bool:
        database = self._database()
        try:
            note = database.get_note(str(note_id))
            if not note or not note["deleted_at"]:
                raise KeyError("Заметка не найдена в корзине")
            database.delete_note_permanently(str(note_id))
        finally:
            database.close()
        return True

    def empty_trash(self) -> int:
        database = self._database()
        try:
            notes = database.list_trash()
            for note in notes:
                database.delete_note_permanently(note["id"])
            return len(notes)
        finally:
            database.close()

    def set_task_completed(self, task_id: str, completed: bool) -> dict[str, Any]:
        if not isinstance(completed, bool):
            raise ValueError("Состояние задачи задано неверно")
        database = self._database()
        try:
            task = database.get_task(str(task_id))
            if not task:
                raise KeyError("Задача не найдена")
            note = database.get_note(task["note_id"])
            if not note or note["deleted_at"] or note["is_archived"]:
                raise KeyError("Задача не найдена")
            return database.update_task(
                str(task_id), completed=int(completed)
            )
        finally:
            database.close()

    def set_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise ValueError("Настройки заданы неверно")
        allowed = {
            "start_with_windows",
            "global_hotkeys",
            "close_to_tray",
            "default_color",
            "default_width",
            "default_height",
            "default_font_size",
            "autosave_delay",
        }
        if set(values) != allowed:
            raise ValueError("Набор настроек неполный или содержит лишние поля")
        if any(
            type(values[key]) is not bool
            for key in ("start_with_windows", "global_hotkeys", "close_to_tray")
        ):
            raise ValueError("Переключатели настроек должны быть логическими")
        if values["default_color"] not in {
            "yellow", "pink", "mint", "blue", "lavender", "peach",
            "gray", "graphite", "cream", "dark",
        }:
            raise ValueError("Неизвестный цвет новых стикеров")
        for key, bounds in {
            "default_width": (220, 900),
            "default_height": (180, 1000),
            "default_font_size": (9, 32),
            "autosave_delay": (300, 5000),
        }.items():
            value = values[key]
            if type(value) is not int or not bounds[0] <= value <= bounds[1]:
                raise ValueError(f"Значение настройки {key} вне допустимого диапазона")
        database = self._database()
        try:
            return database.set_settings(**values)
        finally:
            database.close()

    def close_main(self) -> bool:
        database = self._database()
        try:
            close_to_tray = database.get_settings()["close_to_tray"]
            if not close_to_tray:
                database.set_runtime_value("quit_requested", "1")
        finally:
            database.close()
        self._host.hide_main()
        return True

    def save_all(self) -> bool:
        self._host.save_all()
        return True

    def export_notes(self) -> str | None:
        paths = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="stickly-notes.json",
            file_types=("JSON (*.json)",),
        )
        if not paths:
            return None
        database = self._database()
        try:
            return str(database.export_json(paths[0]))
        finally:
            database.close()

    def import_notes(self) -> int | None:
        paths = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("JSON (*.json)",),
        )
        if not paths:
            return None
        database = self._database()
        try:
            return database.import_json(paths[0])
        finally:
            database.close()

    def backup_database(self) -> str | None:
        paths = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="stickly-backup.sqlite3",
            file_types=("SQLite (*.sqlite3)",),
        )
        if not paths:
            return None
        database = self._database()
        try:
            return str(database.create_backup(paths[0]))
        finally:
            database.close()


class StickerWebViewHost:
    def __init__(self, database_file: str):
        self.database_file = database_file
        self.windows: dict[str, Any] = {}
        self.apis: dict[str, StickerApi] = {}
        self._lock = Lock()
        self._stopping = False
        self.anchor = None
        self.dashboard_window = None
        self.dashboard_api = None
        self.dashboard_visible = False

    def open_note(self, note_id: str) -> bool:
        with self._lock:
            existing = self.windows.get(note_id)
            if existing:
                database = Database(self.database_file)
                try:
                    database.update_note(note_id, is_visible=1)
                finally:
                    database.close()
                existing.show()
                existing.restore()
                return True
            database = Database(self.database_file)
            try:
                note = database.get_note(note_id)
                if not note or note["deleted_at"] or note["is_archived"]:
                    return False
                database.update_note(note_id, is_visible=1)
            finally:
                database.close()
            api = StickerApi(self.database_file, note_id, None, self)
            path = resource_path("app/ui/web/sticker.html")
            window = webview.create_window(
                title="Stickly — заметка",
                url=str(path),
                width=max(300, int(note["width"]) + 44),
                height=max(290, int(note["height"]) + 44),
                x=int(note["x"]),
                y=int(note["y"]),
                resizable=True,
                min_size=(300, 290),
                frameless=True,
                easy_drag=False,
                shadow=False,
                transparent=True,
                on_top=bool(note["always_on_top"]),
                confirm_close=False,
                background_color="#000000",
                js_api=api,
            )
            api._window = window
            self.windows[note_id] = window
            self.apis[note_id] = api
            window.events.closed += lambda: self._window_closed(note_id)
            return True

    def show_main(self) -> bool:
        with self._lock:
            window = self.dashboard_window
            if window is None:
                api = DashboardApi(self.database_file, self)
                path = resource_path("app/ui/web/dashboard.html")
                window = webview.create_window(
                    title="Stickly — заметки и задачи",
                    url=str(path),
                    width=1180,
                    height=780,
                    min_size=(900, 600),
                    resizable=True,
                    frameless=False,
                    on_top=False,
                    confirm_close=False,
                    background_color="#15141B",
                    js_api=api,
                )
                if window is None:
                    raise RuntimeError("Не удалось создать главное окно Stickly")
                api._window = window
                self.dashboard_api = api
                self.dashboard_window = window
                window.events.closed += self._main_closed
                window.events.closing += self._main_closing
            else:
                window.show()
                window.restore()
            self.dashboard_visible = True
            return True

    def save_all(self) -> bool:
        for api in tuple(self.apis.values()):
            api.save_now()
        return True

    def hide_main(self) -> bool:
        with self._lock:
            if self.dashboard_window:
                self.dashboard_window.hide()
            self.dashboard_visible = False
            return True

    def refresh_main(self) -> bool:
        window = self.dashboard_window
        if not window or not self.dashboard_visible:
            return True
        if not window.events.loaded.is_set():
            return True
        window.evaluate_js(
            "window.refreshDashboard && window.refreshDashboard(); true"
        )
        return True

    def show_settings(self) -> bool:
        self.show_main()
        window = self.dashboard_window
        if window and window.events.loaded.is_set():
            window.evaluate_js(
                "window.openSettingsPanel && window.openSettingsPanel(); true"
            )
        else:
            self._open_settings_when_ready()
        return True

    def _open_settings_when_ready(self):
        window = self.dashboard_window
        if not window:
            return
        if window.events.loaded.wait(8):
            window.evaluate_js(
                "window.openSettingsPanel && window.openSettingsPanel(); true"
            )
        else:
            logger.error("Главная панель не загрузилась для открытия настроек")

    def _main_closing(self, _window=None):
        if self._stopping:
            return True
        try:
            if self.dashboard_api:
                self.dashboard_api.close_main()
        except (OSError, sqlite3.Error):
            logger.exception("Не удалось обработать закрытие главной панели")
        return False

    def _main_closed(self):
        self.dashboard_window = None
        self.dashboard_api = None
        self.dashboard_visible = False

    def _window_closed(self, note_id: str):
        with self._lock:
            self.windows.pop(note_id, None)
            self.apis.pop(note_id, None)
        if self._stopping:
            return
        database = Database(self.database_file)
        try:
            note = database.get_note(note_id)
            if note and not note["deleted_at"] and not note["is_archived"]:
                database.update_note(note_id, is_visible=0)
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось сохранить закрытие стикера %s", note_id)
        finally:
            database.close()

    def handle_command(self, command: dict[str, Any]):
        action = command.get("action")
        if action == "ping":
            return True
        if action == "main_show":
            return self.show_main()
        if action == "main_hide":
            return self.hide_main()
        if action == "main_refresh":
            return self.refresh_main()
        if action == "main_settings":
            return self.show_settings()
        if action == "open":
            return self.open_note(str(command["note_id"]))
        if action == "show_all":
            results = [
                self.open_note(str(note_id))
                for note_id in command.get("note_ids", [])
            ]
            return all(results)
        if action == "hide":
            note_id = str(command["note_id"])
            window = self.windows.get(note_id)
            if window:
                api_database = Database(self.database_file)
                try:
                    api_database.update_note(note_id, is_visible=0)
                finally:
                    api_database.close()
                window.hide()
            return True
        if action == "hide_all":
            for note_id, window in tuple(self.windows.items()):
                database = Database(self.database_file)
                try:
                    database.update_note(note_id, is_visible=0)
                finally:
                    database.close()
                window.hide()
            return True
        if action == "save_all":
            for api in tuple(self.apis.values()):
                api.save_now()
            return True
        if action == "quit":
            self._stopping = True
            return True
        raise ValueError(f"Неизвестная команда окон стикеров: {action}")

    def run_pipe_server(self, address: str, authkey: bytes):
        try:
            listener = Listener(address, family="AF_PIPE", authkey=authkey)
        except (OSError, ValueError):
            logger.exception("Не удалось открыть локальный канал окон стикеров")
            return
        try:
            while not self._stopping:
                try:
                    connection = listener.accept()
                except (OSError, EOFError):
                    if self._stopping:
                        break
                    raise
                with connection:
                    try:
                        command = connection.recv()
                        result = self.handle_command(command)
                        connection.send({"ok": True, "result": result})
                        if command.get("action") == "quit":
                            self._destroy_windows()
                            break
                    except (
                        OSError,
                        RuntimeError,
                        ValueError,
                        KeyError,
                        TypeError,
                        sqlite3.Error,
                        JavascriptException,
                    ):
                        logger.exception("Ошибка команды окна стикера")
                        try:
                            connection.send(
                                {"ok": False, "error": "Не удалось выполнить команду"}
                            )
                        except (OSError, EOFError):
                            logger.exception("Не удалось вернуть ошибку вызывающей стороне")
        finally:
            listener.close()

    def _destroy_windows(self):
        if self.dashboard_window:
            self.dashboard_window.destroy()
        for window in tuple(self.windows.values()):
            window.destroy()
        if self.anchor:
            self.anchor.destroy()


def run_webview_host(address: str, authkey: bytes, database_file: str) -> int:
    host = StickerWebViewHost(database_file)
    host.anchor = webview.create_window(
        "Stickly WebView host",
        html="<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>",
        width=1,
        height=1,
        x=-100,
        y=-100,
        hidden=True,
        on_top=False,
        frameless=True,
    )
    server = Thread(
        target=host.run_pipe_server,
        args=(address, authkey),
        name="stickly-webview-ipc",
        daemon=True,
    )
    webview.start(func=server.start, gui="edgechromium", debug=False)
    host._stopping = True
    logger.info("Процесс окон стикеров WebView2 завершён")
    return 0
