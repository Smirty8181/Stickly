from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.database import Database
from app.ui.paper import PAPER_PALETTES, paper_palette
from main import SticklyApplication
from app.ui.main_window import MainWindow
from app.ui.sticker_window import StickerWindow


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "ui.sqlite3")

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_sticker_edits_and_saves_note_and_tasks(self):
        note = self.database.create_note(title="До", body="Текст")
        note["tasks"] = []
        note["autosave_delay"] = 300
        sticker = StickerWindow(self.database, note)
        sticker.title.setText("После")
        sticker.body.setPlainText("Сохранённый текст")
        self.database.add_task(note["id"], "Проверить")
        sticker._render_tasks(self.database.list_tasks(note["id"]))
        sticker.save_now()
        saved = self.database.get_note(note["id"])
        self.assertEqual(saved["title"], "После")
        self.assertEqual(saved["body"], "Сохранённый текст")
        self.assertGreaterEqual(saved["width"], 220)
        self.assertEqual(self.database.list_tasks(note["id"])[0]["text"], "Проверить")
        sticker.deleteLater()

    def test_dashboard_renders_empty_state_and_created_note(self):
        window = MainWindow(self.database)
        self.assertIsNotNone(window.findChild(type(window.heading), "emptyTitle"))
        self.database.create_note(title="Черновик")
        window.refresh()
        titles = window.findChildren(type(window.heading), "noteTitle")
        self.assertTrue(any(label.text() == "Черновик" for label in titles))
        self.assertEqual(window.note_view_mode, "grid")
        window.deleteLater()

    def test_dashboard_switches_between_grid_and_list(self):
        for index in range(4):
            self.database.create_note(title=f"Заметка {index}")
        window = MainWindow(self.database)
        window.resize(1120, 760)
        window.show()
        self.qt_app.processEvents()
        self.assertGreaterEqual(window._rendered_columns, 2)
        window.resize(900, 650)
        self.qt_app.processEvents()
        self.assertEqual(window._rendered_columns, 1)
        window.resize(1120, 760)
        self.qt_app.processEvents()
        self.assertGreaterEqual(window._rendered_columns, 2)
        window.list_button.click()
        self.assertEqual(window.note_view_mode, "list")
        self.assertEqual(window._rendered_columns, 1)
        window.grid_button.click()
        self.assertEqual(window.note_view_mode, "grid")
        window.deleteLater()

    def test_sticker_position_is_recovered_when_off_screen(self):
        note = {"x": 500000, "y": 500000, "width": 300, "height": 320}
        self.assertTrue(SticklyApplication._normalize_position(note))
        screen = self.qt_app.primaryScreen().availableGeometry()
        self.assertTrue(screen.contains(note["x"], note["y"]))

    def test_paper_themes_use_readable_contrasting_text(self):
        self.assertIn("cream", PAPER_PALETTES)
        self.assertTrue(
            {"peach", "gray", "graphite"}.issubset(PAPER_PALETTES)
        )

        def luminance(hex_color):
            channels = [
                int(hex_color[index:index + 2], 16) / 255
                for index in (1, 3, 5)
            ]
            linear = [
                value / 12.92 if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in channels
            ]
            return sum(
                channel * weight
                for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722))
            )

        for color in PAPER_PALETTES:
            palette = paper_palette(color)
            text_lightness = luminance(palette["foreground"])
            for surface in (palette["top"], palette["bottom"]):
                surface_lightness = luminance(surface)
                contrast = (
                    max(text_lightness, surface_lightness) + 0.05
                ) / (min(text_lightness, surface_lightness) + 0.05)
                self.assertGreaterEqual(contrast, 4.5, color)
            self.assertTrue(palette["border"].startswith("#"))
        self.assertEqual(
            paper_palette("custom", "invalid")["foreground"], "#302B3D"
        )


if __name__ == "__main__":
    unittest.main()
