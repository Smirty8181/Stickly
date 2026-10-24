from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.services.web_sticker_host import DashboardApi, StickerApi


class FakeWindow:
    x = 120
    y = 140
    width = 344
    height = 364
    on_top = True

    def __init__(self):
        self.hidden = False

    def hide(self):
        self.hidden = True

    def evaluate_js(self, _script):
        return {"title": "Сохранено перед выходом", "body": "Текст", "font_size": 19}


class FakeHost:
    def __init__(self):
        self.opened_notes = []

    def open_note(self, note_id):
        self.opened_notes.append(note_id)

    def hide(self, _note_id):
        pass

    def save_all(self):
        pass


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "stickly.sqlite3"
        self.host = FakeHost()
        self.api = DashboardApi(str(self.database_file), self.host)
        database = Database(self.database_file)
        self.note = database.create_note(
            title="План на день", body="Купить продукты", color="mint"
        )
        self.task = database.add_task(self.note["id"], "Купить продукты")
        self.archived = database.create_note(title="Старая идея")
        database.update_note(self.archived["id"], is_archived=1)
        database.add_task(self.archived["id"], "Скрытая задача")
        database.close()

    def test_api_exposes_no_internal_state_to_webview(self):
        self.assertFalse(
            [name for name in vars(self.api) if not name.startswith("_")]
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dashboard_filters_notes_and_excludes_archived_tasks(self):
        data = self.api.get_dashboard_data(
            query="продукты", status="active", color="mint"
        )

        self.assertEqual([note["id"] for note in data["notes"]], [self.note["id"]])
        self.assertEqual([task["id"] for task in data["tasks"]], [self.task["id"]])
        self.assertEqual(data["stats"]["active_tasks"], 1)
        self.assertEqual(data["stats"]["notes"], 2)

    def test_dashboard_rejects_unknown_filters_and_invalid_settings(self):
        with self.assertRaises(ValueError):
            self.api.get_dashboard_data(status="deleted")

        database = Database(self.database_file)
        try:
            settings = database.get_settings()
        finally:
            database.close()
        settings["default_width"] = 10
        with self.assertRaises(ValueError):
            self.api.set_settings(settings)

    def test_settings_task_completion_and_trash_operations(self):
        database = Database(self.database_file)
        try:
            settings = database.get_settings()
        finally:
            database.close()
        settings["default_width"] = 420
        self.assertEqual(self.api.set_settings(settings)["default_width"], 420)

        self.api.set_task_completed(self.task["id"], True)
        database = Database(self.database_file)
        try:
            self.assertTrue(database.get_task(self.task["id"])["completed"])
        finally:
            database.close()

        with self.assertRaises(KeyError):
            self.api.delete_note_permanently(self.note["id"])
        self.api.trash_note(self.note["id"])
        self.assertTrue(self.api.delete_note_permanently(self.note["id"]))


class StickerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "stickly.sqlite3"
        database = Database(self.database_file)
        self.note = database.create_note()
        database.close()
        self.window = FakeWindow()
        self.host = FakeHost()
        self.api = StickerApi(
            str(self.database_file), self.note["id"], self.window, self.host
        )

    def tearDown(self):
        if self.api._geometry_timer:
            self.api._geometry_timer.cancel()
        self.temp_dir.cleanup()

    def read_note(self, note_id=None):
        database = Database(self.database_file)
        try:
            return database.get_note(note_id or self.note["id"])
        finally:
            database.close()

    def test_api_exposes_no_internal_state_to_webview(self):
        self.assertFalse(
            [name for name in vars(self.api) if not name.startswith("_")]
        )

    def test_content_is_sanitized_and_saved(self):
        self.assertTrue(
            self.api.save_content(
                self.note["id"], "Заголовок" * 100, "текст", 100
            )
        )

        saved = self.read_note()
        self.assertEqual(saved["title"], "Заголовок" * 55 + "Загол")
        self.assertEqual(saved["body"], "текст")
        self.assertEqual(saved["font_size"], 32)

    def test_theme_and_pin_are_persisted(self):
        self.assertTrue(self.api.set_color(self.note["id"], "custom", "#123ABC"))
        self.assertTrue(self.api.set_pin(self.note["id"], False))

        saved = self.read_note()
        self.assertEqual(saved["color"], "custom")
        self.assertEqual(saved["custom_color"], "#123ABC")
        self.assertEqual(saved["always_on_top"], 0)
        self.assertFalse(self.window.on_top)

    def test_tasks_are_scoped_and_reordered_atomically(self):
        first = self.api.add_task(self.note["id"], "Первая")
        second = self.api.add_task(self.note["id"], "Вторая")

        self.assertTrue(
            self.api.reorder_tasks(self.note["id"], [second["id"], first["id"]])
        )
        with self.assertRaises(ValueError):
            self.api.reorder_tasks(self.note["id"], [first["id"], first["id"]])

        database = Database(self.database_file)
        try:
            tasks = database.list_tasks(self.note["id"])
            self.assertEqual(
                [task["id"] for task in tasks], [second["id"], first["id"]]
            )
        finally:
            database.close()

        with self.assertRaises(ValueError):
            self.api.add_task("another-note", "Чужая")

    def test_task_operations_reject_another_notes_task(self):
        database = Database(self.database_file)
        other_note = database.create_note()
        other_task = database.add_task(other_note["id"], "Чужая задача")
        database.close()

        with self.assertRaises(KeyError):
            self.api.toggle_task(other_task["id"], True)
        with self.assertRaises(KeyError):
            self.api.delete_task(other_task["id"])

    def test_geometry_and_hide_are_saved(self):
        self.assertTrue(self.api.save_geometry())
        self.assertTrue(self.api.hide_sticker(self.note["id"]))

        saved = self.read_note()
        self.assertEqual((saved["x"], saved["y"]), (self.window.x, self.window.y))
        self.assertEqual((saved["width"], saved["height"]), (300, 320))
        self.assertEqual(saved["is_visible"], 0)
        self.assertTrue(self.window.hidden)

    def test_save_now_persists_editor_content_and_geometry(self):
        self.assertTrue(self.api.save_now())

        saved = self.read_note()
        self.assertEqual(saved["title"], "Сохранено перед выходом")
        self.assertEqual(saved["body"], "Текст")
        self.assertEqual(saved["font_size"], 19)

    def test_invalid_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            self.api.set_color(self.note["id"], "not-a-theme")
        with self.assertRaises(ValueError):
            self.api.set_color(self.note["id"], "custom", "red")


if __name__ == "__main__":
    unittest.main()
