from __future__ import annotations

import json
import logging
import re
import random
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

COLORS = {
    "yellow": "#F8E79B",
    "pink": "#F4C8D7",
    "mint": "#C8E8D1",
    "blue": "#C8E1F5",
    "lavender": "#D9D0F3",
    "peach": "#F4D4B7",
    "gray": "#E0DED7",
    "graphite": "#494752",
    "cream": "#F4E6C9",
    "dark": "#343342",
    "custom": "#E9D5FF",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_color": "yellow",
    "default_width": 300,
    "default_height": 320,
    "default_font_size": 14,
    "autosave_delay": 800,
    "start_with_windows": False,
    "global_hotkeys": False,
    "close_to_tray": True,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT 'yellow',
                    custom_color TEXT NOT NULL DEFAULT '#E9D5FF',
                    font_size INTEGER NOT NULL DEFAULT 14,
                    opacity REAL NOT NULL DEFAULT 1,
                    width INTEGER NOT NULL DEFAULT 300,
                    height INTEGER NOT NULL DEFAULT 320,
                    x INTEGER NOT NULL DEFAULT 120,
                    y INTEGER NOT NULL DEFAULT 120,
                    rotation REAL NOT NULL DEFAULT 0,
                    always_on_top INTEGER NOT NULL DEFAULT 1,
                    is_visible INTEGER NOT NULL DEFAULT 1,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS app_runtime (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at);
                CREATE INDEX IF NOT EXISTS idx_tasks_note_position
                    ON tasks(note_id, position);
                PRAGMA user_version = 1;
                """
            )
            columns = {
                row["name"]
                for row in self.connection.execute("PRAGMA table_info(notes)")
            }
            if "rotation" not in columns:
                self.connection.execute(
                    "ALTER TABLE notes ADD COLUMN rotation REAL NOT NULL DEFAULT 0"
                )
            for key, value in DEFAULT_SETTINGS.items():
                self.connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                    (key, json.dumps(value)),
                )

    def close(self) -> None:
        self.connection.close()

    def create_note(
        self,
        *,
        color: str = "yellow",
        width: int = 300,
        height: int = 320,
        font_size: int = 14,
        custom_color: str = "#E9D5FF",
        title: str = "",
        body: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        note_id = str(uuid.uuid4())
        rotation = round(random.uniform(-1.2, 1.2), 2)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO notes(id, title, body, color, custom_color, font_size,
                    width, height, x, y, rotation, is_visible, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 120, 120, ?, 1, ?, ?)
                """,
                (note_id, title, body, color, custom_color, font_size,
                 width, height, rotation, now, now),
            )
        return self.get_note(note_id)

    def get_note(self, note_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        return self._note_dict(row) if row else None

    @staticmethod
    def _note_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["tasks"] = []
        return result

    def list_notes(
        self,
        *,
        query: str = "",
        status: str = "all",
        color: str = "all",
        sort: str = "updated",
    ) -> list[dict[str, Any]]:
        clauses = ["deleted_at IS NULL"]
        params: list[Any] = []
        if status == "active":
            clauses.append("is_archived = 0")
        elif status == "archived":
            clauses.append("is_archived = 1")
        if color != "all":
            clauses.append("color = ?")
            params.append(color)
        if query.strip():
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')"
            )
            escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend((f"%{escaped}%", f"%{escaped}%"))
        order = "created_at DESC" if sort == "created" else "updated_at DESC"
        rows = self.connection.execute(
            f"SELECT * FROM notes WHERE {' AND '.join(clauses)} ORDER BY {order}",
            params,
        ).fetchall()
        notes = [self._note_dict(row) for row in rows]
        for note in notes:
            note["tasks"] = self.list_tasks(note["id"])
        return notes

    def update_note(self, note_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "title", "body", "color", "custom_color", "font_size", "opacity",
            "width", "height", "x", "y", "rotation", "always_on_top", "is_visible",
            "is_archived",
        }
        changes = {key: value for key, value in fields.items() if key in allowed}
        if not changes:
            note = self.get_note(note_id)
            if not note:
                raise KeyError(f"Заметка {note_id} не найдена")
            return note
        changes["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in changes)
        with self.connection:
            cursor = self.connection.execute(
                f"UPDATE notes SET {assignments} WHERE id = ? AND deleted_at IS NULL",
                (*changes.values(), note_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Заметка {note_id} не найдена")
        return self.get_note(note_id)

    def duplicate_note(self, note_id: str) -> dict[str, Any]:
        source = self.get_note(note_id)
        if not source:
            raise KeyError(f"Заметка {note_id} не найдена")
        source["tasks"] = self.list_tasks(note_id)
        duplicate = self.create_note(
            color=source["color"], width=source["width"], height=source["height"],
            font_size=source["font_size"], custom_color=source["custom_color"],
            title=f"{source['title']} — копия" if source["title"] else "Копия",
            body=source["body"],
        )
        self.update_note(
            duplicate["id"], opacity=source["opacity"], rotation=source["rotation"]
        )
        for task in source["tasks"]:
            self.add_task(duplicate["id"], task["text"], completed=task["completed"])
        result = self.get_note(duplicate["id"])
        result["tasks"] = self.list_tasks(duplicate["id"])
        return result

    def soft_delete_note(self, note_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE notes SET deleted_at = ?, is_visible = 0, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NULL",
                (utc_now(), utc_now(), note_id),
            )

    def restore_note(self, note_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE notes SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (utc_now(), note_id),
            )

    def delete_note_permanently(self, note_id: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def list_trash(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM notes WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()
        return [self._note_dict(row) for row in rows]

    def add_task(
        self, note_id: str, text: str, *, completed: bool = False
    ) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("Текст задачи не может быть пустым")
        now = utc_now()
        task_id = str(uuid.uuid4())
        with self.connection:
            position = self.connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE note_id = ?",
                (note_id,),
            ).fetchone()[0]
            self.connection.execute(
                """
                INSERT INTO tasks(id, note_id, text, completed, position, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, note_id, text, int(completed), position, now, now),
            )
            self.connection.execute(
                "UPDATE notes SET updated_at = ? WHERE id = ?", (now, note_id)
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_tasks(self, note_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM tasks WHERE note_id = ? ORDER BY position, created_at",
            (note_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"text", "completed", "position"}
        changes = {key: value for key, value in fields.items() if key in allowed}
        if "text" in changes:
            changes["text"] = changes["text"].strip()
            if not changes["text"]:
                raise ValueError("Текст задачи не может быть пустым")
        changes["updated_at"] = utc_now()
        with self.connection:
            row = self.connection.execute(
                "SELECT note_id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Задача {task_id} не найдена")
            assignments = ", ".join(f"{key} = ?" for key in changes)
            self.connection.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ?",
                (*changes.values(), task_id),
            )
            self.connection.execute(
                "UPDATE notes SET updated_at = ? WHERE id = ?",
                (utc_now(), row["note_id"]),
            )
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> None:
        with self.connection:
            row = self.connection.execute(
                "SELECT note_id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row:
                self.connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                self.connection.execute(
                    "UPDATE notes SET updated_at = ? WHERE id = ?",
                    (utc_now(), row["note_id"]),
                )

    def move_task(self, task_id: str, direction: int) -> None:
        if direction not in (-1, 1):
            raise ValueError("Направление перемещения должно быть -1 или 1")
        tasks = self.connection.execute(
            "SELECT id, note_id, position FROM tasks WHERE note_id = "
            "(SELECT note_id FROM tasks WHERE id = ?) ORDER BY position, created_at",
            (task_id,),
        ).fetchall()
        index = next((i for i, task in enumerate(tasks) if task["id"] == task_id), None)
        if index is None:
            raise KeyError(f"Задача {task_id} не найдена")
        other_index = index + direction
        if not 0 <= other_index < len(tasks):
            return
        now = utc_now()
        first, second = tasks[index], tasks[other_index]
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET position = ?, updated_at = ? WHERE id = ?",
                (second["position"], now, first["id"]),
            )
            self.connection.execute(
                "UPDATE tasks SET position = ?, updated_at = ? WHERE id = ?",
                (first["position"], now, second["id"]),
            )
            self.connection.execute(
                "UPDATE notes SET updated_at = ? WHERE id = ?",
                (now, first["note_id"]),
            )

    def reorder_tasks(self, note_id: str, ordered_ids: list[str]) -> None:
        note = self.get_note(note_id)
        if not note or note["deleted_at"]:
            raise KeyError(f"Заметка {note_id} не найдена")
        tasks = self.list_tasks(note_id)
        task_ids = {task["id"] for task in tasks}
        if len(ordered_ids) != len(task_ids) or set(ordered_ids) != task_ids:
            raise ValueError("Получен некорректный порядок задач")
        now = utc_now()
        with self.connection:
            self.connection.executemany(
                "UPDATE tasks SET position = ?, updated_at = ? "
                "WHERE id = ? AND note_id = ?",
                (
                    (position, now, task_id, note_id)
                    for position, task_id in enumerate(ordered_ids)
                ),
            )
            self.connection.execute(
                "UPDATE notes SET updated_at = ? WHERE id = ?",
                (now, note_id),
            )

    def get_settings(self) -> dict[str, Any]:
        rows = self.connection.execute("SELECT key, value FROM settings").fetchall()
        settings = DEFAULT_SETTINGS.copy()
        settings.update({row["key"]: json.loads(row["value"]) for row in rows})
        return settings

    def set_settings(self, **values: Any) -> dict[str, Any]:
        with self.connection:
            for key, value in values.items():
                self.connection.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
        return self.get_settings()

    def set_runtime_value(self, key: str, value: str) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO app_runtime(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def consume_runtime_value(self, key: str) -> str | None:
        with self.connection:
            row = self.connection.execute(
                "SELECT value FROM app_runtime WHERE key = ?", (key,)
            ).fetchone()
            if row:
                self.connection.execute(
                    "DELETE FROM app_runtime WHERE key = ?", (key,)
                )
                return row["value"]
        return None

    def create_backup(self, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(destination)
        try:
            self.connection.backup(target)
        finally:
            target.close()
        return destination

    def export_json(self, destination: str | Path) -> Path:
        data = {
            "format": "stickly-export",
            "version": 1,
            "exported_at": utc_now(),
            "notes": self.list_notes(),
            "settings": self.get_settings(),
        }
        destination = Path(destination)
        destination.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return destination

    def import_json(self, source: str | Path) -> int:
        source = Path(source)
        if source.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Файл импорта превышает допустимый размер 10 МБ")
        data = json.loads(source.read_text(encoding="utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("format") != "stickly-export"
            or data.get("version") != 1
            or not isinstance(data.get("notes"), list)
        ):
            raise ValueError("Файл не является корректным экспортом Stickly")

        validated: list[dict[str, Any]] = []
        for raw in data["notes"]:
            if not isinstance(raw, dict):
                raise ValueError("В файле найдена заметка неверного формата")
            title, body = raw.get("title", ""), raw.get("body", "")
            tasks = raw.get("tasks", [])
            if (
                not isinstance(title, str) or len(title) > 500
                or not isinstance(body, str) or len(body) > 100_000
                or not isinstance(tasks, list) or len(tasks) > 500
            ):
                raise ValueError("В файле найдена заметка с недопустимыми данными")
            checked_tasks = []
            for task in tasks:
                if (
                    not isinstance(task, dict)
                    or not isinstance(task.get("text", ""), str)
                    or len(task.get("text", "")) > 2000
                ):
                    raise ValueError("В файле найдена задача неверного формата")
                checked_tasks.append(task)
            validated.append({**raw, "title": title, "body": body, "tasks": checked_tasks})

        count = 0
        with self.connection:
            for note in validated:
                color = note.get("color", "yellow")
                if color not in COLORS:
                    color = "yellow"
                width = self._bounded_int(note.get("width"), 300, 220, 900)
                height = self._bounded_int(note.get("height"), 320, 180, 1000)
                font_size = self._bounded_int(note.get("font_size"), 14, 9, 32)
                opacity = note.get("opacity", 1)
                if not isinstance(opacity, (int, float)) or not 0.35 <= opacity <= 1:
                    opacity = 1
                custom_color = note.get("custom_color", "#E9D5FF")
                if (
                    not isinstance(custom_color, str)
                    or not re.fullmatch(r"#[0-9A-Fa-f]{6}", custom_color)
                ):
                    custom_color = "#E9D5FF"
                now = utc_now()
                note_id = str(uuid.uuid4())
                self.connection.execute(
                    """
                    INSERT INTO notes(id, title, body, color, custom_color, font_size,
                        opacity, width, height, x, y, always_on_top, is_visible,
                        is_archived, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 120, 120, 1, 0, 0, ?, ?)
                    """,
                    (note_id, note["title"], note["body"], color,
                     custom_color, font_size,
                     opacity, width, height, now, now),
                )
                for position, task in enumerate(note["tasks"]):
                    text = task.get("text", "").strip()
                    if text:
                        self.connection.execute(
                            """
                            INSERT INTO tasks(id, note_id, text, completed, position,
                                created_at, updated_at)
                            VALUES(?, ?, ?, ?, ?, ?, ?)
                            """,
                            (str(uuid.uuid4()), note_id, text,
                             int(bool(task.get("completed"))), position,
                             now, now),
                        )
                count += 1
        return count

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        return max(minimum, min(maximum, value))
