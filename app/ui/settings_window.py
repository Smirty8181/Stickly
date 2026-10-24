from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from app.database import COLORS


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки Stickly")
        self.setMinimumWidth(390)
        root = QVBoxLayout(self)
        root.setSpacing(16)

        general = QGroupBox("Основные")
        form = QFormLayout(general)
        self.startup = QCheckBox("Запускать вместе с Windows")
        self.startup.setChecked(bool(settings["start_with_windows"]))
        self.hotkeys = QCheckBox("Глобальные сочетания клавиш")
        self.hotkeys.setChecked(bool(settings["global_hotkeys"]))
        self.close_to_tray = QCheckBox("Сворачивать Stickly в трей при закрытии")
        self.close_to_tray.setChecked(bool(settings["close_to_tray"]))
        form.addRow(self.startup)
        form.addRow(self.hotkeys)
        form.addRow(self.close_to_tray)
        form.addRow(QLabel("Новый стикер всегда поверх окон"), QLabel("Да"))
        root.addWidget(general)

        defaults = QGroupBox("Новые стикеры")
        defaults_form = QFormLayout(defaults)
        self.color = QComboBox()
        self.color.addItem("Жёлтый", "yellow")
        self.color.addItem("Розовый", "pink")
        self.color.addItem("Мятный", "mint")
        self.color.addItem("Голубой", "blue")
        self.color.addItem("Лавандовый", "lavender")
        self.color.addItem("Персиковый", "peach")
        self.color.addItem("Серый", "gray")
        self.color.addItem("Графитовый", "graphite")
        self.color.addItem("Кремовый", "cream")
        self.color.addItem("Тёмный", "dark")
        index = self.color.findData(settings["default_color"])
        self.color.setCurrentIndex(max(0, index))

        self.width = QSpinBox()
        self.width.setRange(220, 900)
        self.width.setSuffix(" px")
        self.width.setValue(int(settings["default_width"]))
        self.height = QSpinBox()
        self.height.setRange(180, 1000)
        self.height.setSuffix(" px")
        self.height.setValue(int(settings["default_height"]))
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 32)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(int(settings["default_font_size"]))
        self.autosave = QSpinBox()
        self.autosave.setRange(300, 5000)
        self.autosave.setSingleStep(100)
        self.autosave.setSuffix(" мс")
        self.autosave.setValue(int(settings["autosave_delay"]))
        defaults_form.addRow("Цвет", self.color)
        defaults_form.addRow("Ширина", self.width)
        defaults_form.addRow("Высота", self.height)
        defaults_form.addRow("Размер текста", self.font_size)
        defaults_form.addRow("Задержка автосохранения", self.autosave)
        root.addWidget(defaults)
        root.addWidget(
            QLabel(
                "Горячие клавиши: Alt+Ctrl+N — новый стикер, "
                "Alt+Ctrl+H — Stickly, Alt+Ctrl+S — показать/скрыть стикеры."
            )
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict:
        return {
            "start_with_windows": self.startup.isChecked(),
            "global_hotkeys": self.hotkeys.isChecked(),
            "close_to_tray": self.close_to_tray.isChecked(),
            "default_color": self.color.currentData(),
            "default_width": self.width.value(),
            "default_height": self.height.value(),
            "default_font_size": self.font_size.value(),
            "autosave_delay": self.autosave.value(),
        }
