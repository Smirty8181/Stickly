from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.database import Database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "test.sqlite3")

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_create_update_and_restore_note(self):
        note = self.database.create_note(title="План", body="Текст")
        self.assertEqual(note["title"], "План")
        self.database.update_note(note["id"], title="Новый план", x=400, y=300)
        self.assertEqual(self.database.get_note(note["id"])["title"], "Новый план")
        self.database.soft_delete_note(note["id"])
        self.assertEqual(self.database.list_notes(), [])
        self.database.restore_note(note["id"])
        self.assertEqual(len(self.database.list_notes()), 1)

    def test_tasks_are_saved_and_can_be_completed(self):
        note = self.database.create_note()
        task = self.database.add_task(note["id"], "Позвонить")
        second = self.database.add_task(note["id"], "Подготовить список")
        self.database.move_task(second["id"], -1)
        self.assertEqual(
            [item["text"] for item in self.database.list_tasks(note["id"])],
            ["Подготовить список", "Позвонить"],
        )
        self.database.update_task(task["id"], completed=1)
        self.assertEqual(self.database.get_task(task["id"])["completed"], 1)
        self.database.delete_task(task["id"])
        self.assertEqual(
            [item["text"] for item in self.database.list_tasks(note["id"])],
            ["Подготовить список"],
        )

    def test_settings_round_trip(self):
        self.database.set_settings(default_color="mint", autosave_delay=1200)
        settings = self.database.get_settings()
        self.assertEqual(settings["default_color"], "mint")
        self.assertEqual(settings["autosave_delay"], 1200)
        self.assertEqual(settings["global_hotkeys"], False)

    def test_duplicate_copies_note_and_tasks(self):
        source = self.database.create_note(title="Оригинал", body="Текст")
        self.database.add_task(source["id"], "Дело", completed=True)
        duplicate = self.database.duplicate_note(source["id"])
        self.assertNotEqual(source["id"], duplicate["id"])
        self.assertEqual(duplicate["title"], "Оригинал — копия")
        self.assertEqual(duplicate["tasks"][0]["text"], "Дело")
        self.assertEqual(duplicate["tasks"][0]["completed"], 1)

    def test_export_import_preserves_existing_notes(self):
        original = self.database.create_note(title="Моя заметка", body="Содержимое")
        self.database.add_task(original["id"], "Пункт", completed=True)
        export = Path(self.temp.name) / "notes.json"
        self.database.export_json(export)

        other = Database(Path(self.temp.name) / "other.sqlite3")
        try:
            imported = other.import_json(export)
            self.assertEqual(imported, 1)
            notes = other.list_notes()
            self.assertEqual(notes[0]["title"], "Моя заметка")
            self.assertEqual(notes[0]["tasks"][0]["completed"], 1)
            self.assertEqual(other.import_json(export), 1)
            self.assertEqual(len(other.list_notes()), 2)
        finally:
            other.close()

    def test_invalid_import_is_rejected_without_changing_data(self):
        existing = self.database.create_note(title="Оставить")
        path = Path(self.temp.name) / "invalid.json"
        path.write_text(json.dumps({"format": "wrong", "notes": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.database.import_json(path)
        self.assertEqual([note["id"] for note in self.database.list_notes()], [existing["id"]])

    def test_import_sanitizes_color_and_preserves_task_order(self):
        path = Path(self.temp.name) / "colors.json"
        path.write_text(
            json.dumps(
                {
                    "format": "stickly-export",
                    "version": 1,
                    "notes": [
                        {
                            "title": "Цвет",
                            "body": "",
                            "color": "invalid",
                            "custom_color": '"; color: red;',
                            "tasks": [{"text": "Первый"}, {"text": "Второй"}],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.database.import_json(path)
        note = self.database.list_notes()[0]
        self.assertEqual(note["color"], "yellow")
        self.assertEqual(note["custom_color"], "#E9D5FF")
        self.assertEqual([task["position"] for task in note["tasks"]], [0, 1])

    def test_backup_is_a_valid_database(self):
        note = self.database.create_note(title="Backup")
        backup_path = self.database.create_backup(Path(self.temp.name) / "backup.sqlite3")
        backup = Database(backup_path)
        try:
            self.assertEqual(backup.get_note(note["id"])["title"], "Backup")
        finally:
            backup.close()


if __name__ == "__main__":
    unittest.main()
