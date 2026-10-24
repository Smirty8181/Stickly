from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.ui.paper import PaperSurface, paper_palette

logger = logging.getLogger(__name__)


class StickerWindow(QWidget):
    changed = Signal()

    def __init__(self, database: Database, note: dict, parent=None):
        super().__init__(parent)
        self.database = database
        self.note_id = note["id"]
        self._note = note
        self._drag_offset = None
        self._loading = True
        self._hidden_by_app = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_content)
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(250)
        self._geometry_timer.timeout.connect(self._save_geometry)

        self.setWindowTitle("Stickly — заметка")
        self.setWindowFlags(self._window_flags(note["always_on_top"]))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(note["width"], note["height"])
        self.move(note["x"], note["y"])

        self.card = PaperSurface(self)
        self.card.setObjectName("stickerCard")
        self.card.setGraphicsEffect(self._shadow())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(15, 15, 15, 15)
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 14, 18, 13)
        layout.setSpacing(7)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.drag_handle = QLabel("●  STICKLY")
        self.drag_handle.setObjectName("stickerBrand")
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.installEventFilter(self)
        header.addWidget(self.drag_handle)
        header.addStretch()
        self.pin_button = QPushButton("↑")
        self.pin_button.setToolTip("Поверх остальных окон")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(bool(note["always_on_top"]))
        self.pin_button.clicked.connect(self._toggle_pin)
        self.color_button = QPushButton("●")
        self.color_button.setToolTip("Изменить цвет")
        self.color_button.clicked.connect(self._choose_color)
        self.hide_button = QPushButton("—")
        self.hide_button.setToolTip("Скрыть заметку")
        self.hide_button.clicked.connect(self.hide_sticker)
        for button in (self.pin_button, self.color_button, self.hide_button):
            button.setObjectName("stickerTool")
            button.setFixedSize(32, 30)
            header.addWidget(button)
        layout.addLayout(header)

        self.title = QLineEdit(note["title"])
        self.title.setObjectName("stickerTitle")
        self.title.setPlaceholderText("Заголовок")
        self.title.setMaxLength(500)
        self.title.textChanged.connect(self._content_changed)
        self.title.setMinimumHeight(34)
        layout.addWidget(self.title)

        self.body = QTextEdit()
        self.body.setObjectName("stickerBody")
        self.body.setPlaceholderText("Запишите важное — стикер сохранит изменения автоматически")
        self.body.setAcceptRichText(False)
        self.body.setPlainText(note["body"])
        self.body.textChanged.connect(self._content_changed)
        layout.addWidget(self.body, 1)

        task_panel = QFrame()
        task_panel.setObjectName("taskPanel")
        task_panel_layout = QVBoxLayout(task_panel)
        task_panel_layout.setContentsMargins(10, 7, 10, 6)
        task_panel_layout.setSpacing(4)
        task_header = QHBoxLayout()
        task_heading = QLabel("Задачи")
        task_heading.setObjectName("taskHeading")
        task_header.addWidget(task_heading)
        task_header.addStretch()
        self.task_count = QLabel()
        self.task_count.setObjectName("taskCount")
        task_header.addWidget(self.task_count)
        task_panel_layout.addLayout(task_header)

        self.tasks_scroll = QScrollArea()
        self.tasks_scroll.setObjectName("tasksScroll")
        self.tasks_scroll.setWidgetResizable(True)
        self.tasks_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tasks_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.tasks_scroll.viewport().setStyleSheet("background: transparent;")
        self.tasks_scroll.setMaximumHeight(126)
        self.tasks_scroll.hide()
        self.tasks_content = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_content)
        self.tasks_layout.setContentsMargins(0, 0, 0, 0)
        self.tasks_layout.setSpacing(2)
        self.tasks_layout.addStretch()
        self.tasks_scroll.setWidget(self.tasks_content)
        task_panel_layout.addWidget(self.tasks_scroll)
        self.task_input = QLineEdit()
        self.task_input.setObjectName("taskInput")
        self.task_input.setPlaceholderText("+ Добавить пункт и нажать Enter")
        self.task_input.returnPressed.connect(self._add_task)
        task_panel_layout.addWidget(self.task_input)
        layout.addWidget(task_panel)

        footer = QHBoxLayout()
        self.updated = QLabel()
        self.updated.setObjectName("stickerFooter")
        footer.addWidget(self.updated)
        footer.addStretch()
        footer.addWidget(QSizeGrip(self))
        layout.addLayout(footer)
        self._build_context_menu()
        self._apply_color(note["color"], note["custom_color"])
        self._set_font_size(note["font_size"])
        self.setWindowOpacity(max(0.35, min(1.0, float(note["opacity"]))))
        self._render_tasks(note.get("tasks", []))
        self._update_task_count(note.get("tasks", []))
        self._loading = False

    @staticmethod
    def _window_flags(always_on_top: bool):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    @staticmethod
    def _shadow():
        effect = QGraphicsDropShadowEffect()
        effect.setBlurRadius(28)
        effect.setOffset(0, 8)
        effect.setColor(QColor(19, 17, 35, 60))
        return effect

    def _build_context_menu(self):
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        actions = (
            ("Новая заметка", self._create_note_requested),
            ("Дублировать", self._duplicate),
            ("Переместить в архив", self._archive),
            ("В корзину", self._trash),
            ("Размер текста +", lambda: self._change_font(1)),
            ("Размер текста −", lambda: self._change_font(-1)),
        )
        for label, callback in actions:
            action = QAction(label, self)
            action.triggered.connect(callback)
            self.addAction(action)

    def set_callbacks(self, *, on_duplicate, on_archive, on_trash, on_new):
        self._on_duplicate = on_duplicate
        self._on_archive = on_archive
        self._on_trash = on_trash
        self._on_new = on_new

    def _create_note_requested(self):
        callback = getattr(self, "_on_new", None)
        if callback:
            callback()

    def _duplicate(self):
        callback = getattr(self, "_on_duplicate", None)
        if callback:
            callback(self.note_id)

    def _archive(self):
        callback = getattr(self, "_on_archive", None)
        if callback:
            callback(self.note_id)

    def _trash(self):
        callback = getattr(self, "_on_trash", None)
        if callback:
            callback(self.note_id)

    def _apply_color(self, color: str, custom_color: str):
        self._note["color"] = color
        self._note["custom_color"] = custom_color
        palette = paper_palette(color, custom_color)
        foreground = palette["foreground"]
        muted = palette["muted"]
        accent = palette["accent"]
        self.card.set_paper(color, custom_color)
        self.card.setStyleSheet(
            f"""
            QFrame#stickerCard {{ background: transparent; border: none; }}
            QLineEdit#stickerTitle, QTextEdit#stickerBody, QLineEdit#taskInput {{
                color: {foreground}; background: transparent; border: none;
                selection-background-color: {accent};
            }}
            QLineEdit#stickerTitle {{ font-size: 17px; font-weight: 700;
                border-bottom: 1px solid {palette['border']}; padding: 4px 0; }}
            QTextEdit#stickerBody {{ font-size: {self._note['font_size']}pt;
                padding: 5px 0; }}
            QLineEdit#taskInput {{ color: {foreground}; padding: 8px 3px 4px;
                border-top: 1px solid {palette['border']}; }}
            QLineEdit#taskInput::placeholder {{ color: {muted}; }}
            QLabel#stickerBrand {{ color: {muted}; font-size: 10px;
                font-weight: 700; letter-spacing: 1px; }}
            QLabel#stickerFooter, QLabel#taskCount {{
                color: {muted}; font-size: 11px; }}
            QLabel#taskHeading {{ color: {foreground}; font-size: 12px;
                font-weight: 700; }}
            QFrame#taskPanel {{ background: rgba(255, 255, 255, 0.16);
                border: 1px solid {palette['border']}; border-radius: 7px; }}
            QPushButton#stickerTool {{ color: {foreground}; background: transparent;
                border: 1px solid transparent; border-radius: 7px; font-size: 15px; }}
            QPushButton#stickerTool:hover, QPushButton#stickerTool:checked {{
                background: rgba(50, 43, 61, 0.12);
                border-color: rgba(50, 43, 61, 0.12); }}
            QCheckBox {{ color: {foreground}; spacing: 8px; padding: 3px 0;
                font-size: 11px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; }}
            QCheckBox::indicator:unchecked {{ border: 1px solid {muted};
                border-radius: 4px; background: rgba(255,255,255,0.20); }}
            QCheckBox::indicator:checked {{ border: 1px solid {accent};
                border-radius: 4px; background: {accent}; }}
            QScrollArea#tasksScroll {{ background: transparent; }}
            """
        )

    def _set_font_size(self, size: int):
        font = self.body.font()
        font.setPointSize(size)
        self.body.setFont(font)
        self._note["font_size"] = size

    def _content_changed(self):
        if not self._loading:
            self._save_timer.start(int(self._note.get("autosave_delay", 800)))
            self.updated.setText("Есть несохранённые изменения…")

    def _save_content(self):
        try:
            self.database.update_note(
                self.note_id,
                title=self.title.text(),
                body=self.body.toPlainText(),
                font_size=self._note["font_size"],
            )
            self.updated.setText("Сохранено")
            self.changed.emit()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось сохранить заметку %s", self.note_id)
            self.updated.setText("Ошибка сохранения")

    def save_now(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_content()
        self._save_geometry()

    def _save_geometry(self):
        try:
            self.database.update_note(
                self.note_id,
                x=self.x(),
                y=self.y(),
                width=self.width(),
                height=self.height(),
                opacity=round(self.windowOpacity(), 2),
            )
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось сохранить положение заметки %s", self.note_id)

    def _toggle_pin(self, enabled: bool):
        self._note["always_on_top"] = int(enabled)
        self.setWindowFlags(self._window_flags(enabled))
        self.show()
        try:
            self.database.update_note(self.note_id, always_on_top=int(enabled))
        except sqlite3.Error:
            logger.exception("Не удалось сохранить состояние закрепления")
            self._note["always_on_top"] = int(not enabled)
            self.pin_button.setChecked(not enabled)
            self.setWindowFlags(self._window_flags(not enabled))
            self.show()
            self.updated.setText("Ошибка сохранения")

    def _choose_color(self):
        menu = QMenu(self)
        labels = {
            "yellow": "Жёлтый", "pink": "Розовый", "mint": "Мятный",
            "blue": "Голубой", "lavender": "Лавандовый",
            "cream": "Кремовый", "dark": "Тёмный",
        }
        for color, label in labels.items():
            action = menu.addAction(f"●  {label}")
            action.triggered.connect(
                lambda checked=False, key=color: self._set_color(key)
            )
        menu.addSeparator()
        custom = menu.addAction("Выбрать свой цвет…")
        custom.triggered.connect(self._choose_custom_color)
        menu.exec(self.color_button.mapToGlobal(self.color_button.rect().bottomLeft()))

    def _set_color(self, color: str, custom_color: str | None = None):
        custom = custom_color or self._note["custom_color"]
        previous = (self._note["color"], self._note["custom_color"])
        self._apply_color(color, custom)
        try:
            self.database.update_note(self.note_id, color=color, custom_color=custom)
        except sqlite3.Error:
            logger.exception("Не удалось сохранить цвет стикера")
            self._apply_color(*previous)
            self.updated.setText("Ошибка сохранения")
            return
        self.changed.emit()

    def _choose_custom_color(self):
        selected = QColorDialog.getColor(
            QColor(self._note["custom_color"]), self, "Цвет стикера"
        )
        if selected.isValid():
            self._set_color("custom", selected.name())

    def _change_font(self, amount: int):
        size = max(9, min(32, self._note["font_size"] + amount))
        self._set_font_size(size)
        self._apply_color(self._note["color"], self._note["custom_color"])
        self._save_timer.start()

    def _add_task(self):
        text = self.task_input.text().strip()
        if not text:
            return
        try:
            self.database.add_task(self.note_id, text)
            self.task_input.clear()
            tasks = self.database.list_tasks(self.note_id)
            self._render_tasks(tasks)
            self._update_task_count(tasks)
            self.changed.emit()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось добавить задачу в заметку %s", self.note_id)

    def _render_tasks(self, tasks: list[dict]):
        while self.tasks_layout.count() > 1:
            item = self.tasks_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.tasks_scroll.setVisible(bool(tasks))
        self.tasks_scroll.setMaximumHeight(min(126, 32 * len(tasks) + 8))
        for task in tasks:
            row = QWidget()
            row.setObjectName("taskRow")
            row.setStyleSheet("background: transparent;")
            row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            row.customContextMenuRequested.connect(
                lambda point, task_id=task["id"], widget=row:
                self._task_menu(widget, point, task_id)
            )
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            checkbox = QCheckBox(task["text"])
            checkbox.setChecked(bool(task["completed"]))
            font = QFont(checkbox.font())
            font.setPointSize(10)
            font.setStrikeOut(bool(task["completed"]))
            checkbox.setFont(font)
            checkbox.toggled.connect(
                lambda checked, task_id=task["id"], box=checkbox:
                self._toggle_task(task_id, checked, box)
            )
            remove = QPushButton("×")
            remove.setObjectName("stickerTool")
            remove.setFixedSize(26, 24)
            remove.clicked.connect(
                lambda checked=False, task_id=task["id"]: self._remove_task(task_id)
            )
            row_layout.addWidget(checkbox, 1)
            row_layout.addWidget(remove)
            self.tasks_layout.insertWidget(self.tasks_layout.count() - 1, row)

    def _task_menu(self, widget: QWidget, point, task_id: str):
        menu = QMenu(self)
        move_up = menu.addAction("Переместить выше")
        move_down = menu.addAction("Переместить ниже")
        action = menu.exec(widget.mapToGlobal(point))
        if action == move_up:
            self._move_task(task_id, -1)
        elif action == move_down:
            self._move_task(task_id, 1)

    def _toggle_task(
        self, task_id: str, completed: bool, checkbox: QCheckBox | None = None
    ):
        try:
            self.database.update_task(task_id, completed=int(completed))
            if checkbox:
                font = checkbox.font()
                font.setStrikeOut(completed)
                checkbox.setFont(font)
            tasks = self.database.list_tasks(self.note_id)
            self._update_task_count(tasks)
            self.changed.emit()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось изменить задачу %s", task_id)

    def _remove_task(self, task_id: str):
        try:
            self.database.delete_task(task_id)
            tasks = self.database.list_tasks(self.note_id)
            self._render_tasks(tasks)
            self._update_task_count(tasks)
            self.changed.emit()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось удалить задачу %s", task_id)

    def _move_task(self, task_id: str, direction: int):
        try:
            self.database.move_task(task_id, direction)
            tasks = self.database.list_tasks(self.note_id)
            self._render_tasks(tasks)
            self._update_task_count(tasks)
            self.changed.emit()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось изменить порядок задач %s", task_id)

    def _update_task_count(self, tasks: list[dict]):
        done = sum(bool(task["completed"]) for task in tasks)
        self.task_count.setText(f"{done}/{len(tasks)}")

    def hide_sticker(self):
        self.save_now()
        self.database.update_note(self.note_id, is_visible=0)
        self._hidden_by_app = True
        self.hide()
        self.changed.emit()

    def show_sticker(self):
        self.database.update_note(self.note_id, is_visible=1)
        self._hidden_by_app = False
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.save_now()
        self.database.update_note(self.note_id, is_visible=0)
        event.accept()
        self.changed.emit()

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._loading:
            self._geometry_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._loading:
            self._geometry_timer.start()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.drag_handle:
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse_event = event
                if mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._drag_offset = (
                        mouse_event.globalPosition().toPoint()
                        - self.frameGeometry().topLeft()
                    )
                    return True
            elif event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                mouse_event = event
                if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(mouse_event.globalPosition().toPoint() - self._drag_offset)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                self._geometry_timer.start()
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_offset = None
        self._geometry_timer.start()
        super().mouseReleaseEvent(event)
