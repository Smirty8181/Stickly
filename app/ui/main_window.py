from __future__ import annotations

import logging
import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.database import Database
from app.paths import resource_path
from app.ui.paper import paper_palette

logger = logging.getLogger(__name__)


class PaperStackIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(66, 52)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        papers = (
            (QColor("#CBBBF0"), 20, 2, 34, 42),
            (QColor("#F1CED8"), 9, 8, 36, 40),
            (QColor("#FFF0B1"), 15, 14, 39, 34),
        )
        for color, x, y, width, height in papers:
            painter.setBrush(color)
            painter.setPen(QPen(color.darker(118), 1))
            painter.drawRoundedRect(x, y, width, height, 4, 4)
        painter.setPen(QPen(QColor("#9C8448"), 1))
        painter.drawLine(23, 26, 44, 26)
        painter.drawLine(23, 32, 39, 32)


class MainWindow(QMainWindow):
    createRequested = Signal()
    openRequested = Signal(str)
    settingsRequested = Signal()
    exportRequested = Signal()
    importRequested = Signal()
    backupRequested = Signal()
    saveAllRequested = Signal()
    closeRequested = Signal()

    def __init__(self, database: Database):
        super().__init__()
        self.database = database
        self.active_status = "all"
        self.note_view_mode = "grid"
        self._visible_notes: list[dict] = []
        self._rendered_columns = 0
        self._rendered_rows = 0
        self.setWindowTitle("Stickly — заметки и задачи")
        self.setMinimumSize(900, 600)
        self.resize(1120, 760)
        self.setWindowIcon(QIcon(resource_path("assets/stickly-logo.ico").as_posix()))

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 22, 16, 20)
        side.setSpacing(12)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setPixmap(self._load_logo())
        brand.addWidget(logo)
        name = QLabel("Stickly")
        name.setObjectName("brandName")
        brand.addWidget(name)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(18)

        self.create_button = QPushButton("+   Новый стикер")
        self.create_button.setObjectName("primaryButton")
        self.create_button.clicked.connect(self.createRequested.emit)
        side.addWidget(self.create_button)
        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        self.notes_navigation = self._nav_button("Все заметки", "all")
        self.active_navigation = self._nav_button("Активные", "active")
        self.archive_navigation = self._nav_button("Архив", "archived")
        for button in (self.notes_navigation, self.active_navigation, self.archive_navigation):
            side.addWidget(button)
        side.addSpacing(18)
        side.addWidget(QLabel("СТАТИСТИКА", objectName="eyebrow"))
        stats_panel = QFrame()
        stats_panel.setObjectName("statsPanel")
        stats_layout = QVBoxLayout(stats_panel)
        stats_layout.setContentsMargins(12, 10, 12, 10)
        stats_layout.setSpacing(4)
        self.note_stat = QLabel("0 заметок")
        self.task_stat = QLabel("0 активных задач")
        self.done_stat = QLabel("0 выполнено")
        for label in (self.note_stat, self.task_stat, self.done_stat):
            label.setObjectName("sidebarStat")
            stats_layout.addWidget(label)
        side.addWidget(stats_panel)
        side.addStretch()

        tools = QHBoxLayout()
        self.settings_button = QPushButton("⚙  Настройки")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        tools.addWidget(self.settings_button)
        side.addLayout(tools)
        data_tools = QHBoxLayout()
        self.export_button = QPushButton("Экспорт")
        self.export_button.clicked.connect(self.exportRequested.emit)
        self.import_button = QPushButton("Импорт")
        self.import_button.clicked.connect(self.importRequested.emit)
        data_tools.addWidget(self.export_button)
        data_tools.addWidget(self.import_button)
        side.addLayout(data_tools)
        self.backup_button = QPushButton("Создать резервную копию")
        self.backup_button.clicked.connect(self.backupRequested.emit)
        side.addWidget(self.backup_button)
        layout.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 26, 32, 24)
        content_layout.setSpacing(16)
        heading = QHBoxLayout()
        title_block = QVBoxLayout()
        self.heading = QLabel("Мои заметки")
        self.heading.setObjectName("pageTitle")
        self.subheading = QLabel("Мысли и дела — собраны в одном месте.")
        self.subheading.setObjectName("mutedText")
        title_block.addWidget(self.heading)
        title_block.addWidget(self.subheading)
        heading.addLayout(title_block)
        heading.addStretch()
        self.new_button = QPushButton("+  Создать стикер")
        self.new_button.setObjectName("primaryButton")
        self.new_button.clicked.connect(self.createRequested.emit)
        heading.addWidget(self.new_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        content_layout.addLayout(heading)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("contentTabs")
        self.notes_page = QWidget()
        notes_layout = QVBoxLayout(self.notes_page)
        notes_layout.setContentsMargins(0, 12, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("Поиск по заголовку и содержимому")
        self.search.textChanged.connect(self.refresh)
        self.color_filter = QComboBox()
        self.color_filter.addItem("Все цвета", "all")
        color_names = {
            "yellow": "Жёлтый", "pink": "Розовый", "mint": "Мятный",
            "blue": "Голубой", "lavender": "Лавандовый",
            "peach": "Персиковый", "gray": "Серый",
            "graphite": "Графитовый", "cream": "Кремовый",
            "dark": "Тёмный",
            "custom": "Свой",
        }
        for color, label in color_names.items():
            self.color_filter.addItem(label, color)
        self.color_filter.currentIndexChanged.connect(self.refresh)
        self.sort_filter = QComboBox()
        self.sort_filter.addItem("Сначала изменённые", "updated")
        self.sort_filter.addItem("Сначала созданные", "created")
        self.sort_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.color_filter)
        filters.addWidget(self.sort_filter)
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.grid_button = QPushButton("Сетка")
        self.grid_button.setObjectName("viewButton")
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        self.list_button = QPushButton("Список")
        self.list_button.setObjectName("viewButton")
        self.list_button.setCheckable(True)
        self.view_group.addButton(self.grid_button)
        self.view_group.addButton(self.list_button)
        self.grid_button.clicked.connect(lambda: self._set_view_mode("grid"))
        self.list_button.clicked.connect(lambda: self._set_view_mode("list"))
        filters.addWidget(self.grid_button)
        filters.addWidget(self.list_button)
        notes_layout.addLayout(filters)
        self.notes_scroll = QScrollArea()
        self.notes_scroll.setWidgetResizable(True)
        self.notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.notes_scroll.setObjectName("notesScroll")
        self.notes_scroll.viewport().setStyleSheet("background: transparent;")
        self.notes_container = QWidget()
        self.notes_container.setObjectName("notesContainer")
        self.notes_container.setStyleSheet("background: transparent;")
        self.notes_grid_layout = QGridLayout(self.notes_container)
        self.notes_grid_layout.setContentsMargins(0, 8, 0, 12)
        self.notes_grid_layout.setHorizontalSpacing(12)
        self.notes_grid_layout.setVerticalSpacing(12)
        self.notes_scroll.setWidget(self.notes_container)
        notes_layout.addWidget(self.notes_scroll, 1)
        self.tabs.addTab(self.notes_page, "Заметки")

        task_page = QWidget()
        task_layout = QVBoxLayout(task_page)
        task_layout.setContentsMargins(0, 12, 0, 0)
        self.task_filter = QComboBox()
        self.task_filter.addItem("Все задачи", "all")
        self.task_filter.addItem("Активные", "active")
        self.task_filter.addItem("Выполненные", "completed")
        self.task_filter.currentIndexChanged.connect(self._refresh_tasks)
        task_layout.addWidget(self.task_filter)
        self.tasks_list = QListWidget()
        self.tasks_list.setObjectName("tasksList")
        self.tasks_list.itemChanged.connect(self._task_item_changed)
        task_layout.addWidget(self.tasks_list, 1)
        self.tabs.addTab(task_page, "Задачи")

        self.trash_list = QListWidget()
        self.trash_list.setObjectName("trashList")
        self.trash_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.trash_list.customContextMenuRequested.connect(self._trash_menu)
        self.tabs.addTab(self.trash_list, "Корзина")
        content_layout.addWidget(self.tabs, 1)
        layout.addWidget(content, 1)

        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.createRequested.emit)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.saveAllRequested.emit)
        self.refresh()

    @staticmethod
    def _load_logo():
        from PySide6.QtGui import QPixmap

        return QPixmap(resource_path("assets/stickly-logo.jpg").as_posix()).scaled(
            38, 38, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _nav_button(self, label: str, status: str) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("navigationButton")
        button.setCheckable(True)
        button.setProperty("status", status)
        if status == self.active_status:
            button.setChecked(True)
        self.navigation_group.addButton(button)
        button.clicked.connect(lambda: self._set_status(status))
        return button

    def _set_status(self, status: str):
        self.active_status = status
        for button in self.navigation_group.buttons():
            button.setChecked(button.property("status") == status)
        labels = {"all": "Мои заметки", "active": "Активные заметки", "archived": "Архив"}
        self.heading.setText(labels[status])
        self.refresh()

    def _set_view_mode(self, mode: str):
        self.note_view_mode = mode
        self._render_note_cards(self._visible_notes)

    def refresh(self, *_):
        query = self.search.text() if hasattr(self, "search") else ""
        color = self.color_filter.currentData() if hasattr(self, "color_filter") else "all"
        sort = self.sort_filter.currentData() if hasattr(self, "sort_filter") else "updated"
        notes = self.database.list_notes(
            query=query, status=self.active_status, color=color, sort=sort
        )
        self._visible_notes = notes
        self._render_note_cards(notes)

        self._refresh_stats(notes)
        self._refresh_tasks()
        self._refresh_trash()

    def _column_count(self) -> int:
        if self.note_view_mode == "list":
            return 1
        return max(1, (self.notes_scroll.viewport().width() + 12) // 330)

    def _render_note_cards(self, notes: list[dict]):
        while self.notes_grid_layout.count():
            item = self.notes_grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        for row in range(self._rendered_rows):
            self.notes_grid_layout.setRowStretch(row, 0)
        for column in range(self._rendered_columns):
            self.notes_grid_layout.setColumnStretch(column, 0)
        columns = self._column_count()
        for column in range(columns):
            self.notes_grid_layout.setColumnStretch(column, 1)
        if not notes:
            empty = QFrame()
            empty.setObjectName("emptyState")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(26, 28, 26, 28)
            empty_layout.setSpacing(8)
            empty_title = QLabel("Здесь пока пусто")
            empty_title.setObjectName("emptyTitle")
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_message = QLabel(
                "Создайте первый стикер: он появится отдельным окном "
                "и будет доступен на рабочем столе."
            )
            empty_message.setWordWrap(True)
            empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_message.setObjectName("mutedText")
            illustration = PaperStackIcon()
            empty_button = QPushButton("Создать стикер")
            empty_button.setObjectName("primaryButton")
            empty_button.clicked.connect(self.createRequested.emit)
            empty_layout.addWidget(
                illustration, alignment=Qt.AlignmentFlag.AlignCenter
            )
            empty_layout.addWidget(empty_title)
            empty_layout.addWidget(empty_message)
            empty_layout.addWidget(empty_button, alignment=Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(250)
            self.notes_grid_layout.addWidget(empty, 0, 0, 1, columns)
            self._rendered_columns = columns
            self._rendered_rows = 1
            return
        for index, note in enumerate(notes):
            row, column = divmod(index, columns)
            self.notes_grid_layout.addWidget(
                self._note_card(note, grid=self.note_view_mode == "grid"),
                row,
                column,
            )
        rows = (len(notes) + columns - 1) // columns
        self.notes_grid_layout.setRowStretch(rows, 1)
        self._rendered_columns = columns
        self._rendered_rows = rows + 1

    def _note_card(self, note: dict, *, grid: bool) -> QWidget:
        card = QFrame()
        card.setObjectName("noteCard")
        palette = paper_palette(note["color"], note["custom_color"])
        card.setStyleSheet(
            f"""
            QFrame#noteCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {palette['top']}, stop:1 {palette['bottom']});
                border: 1px solid {palette['border']};
                border-radius: 10px;
            }}
            QFrame#noteCard:hover {{ border-color: {palette['accent']}; }}
            """
        )
        card.setMinimumHeight(188 if grid else 94)
        card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda point, widget=card, note_id=note["id"]: self._note_menu(widget, point, note_id)
        )
        layout = QVBoxLayout(card) if grid else QHBoxLayout(card)
        layout.setContentsMargins(15, 13, 13, 12)
        layout.setSpacing(9)
        stripe = QFrame()
        stripe.setStyleSheet(
            f"background: {palette['accent']}; border-radius: 2px;"
        )
        if grid:
            stripe.setFixedHeight(4)
            layout.addWidget(stripe)
        else:
            stripe.setFixedWidth(5)
            layout.addWidget(stripe)
        info = QVBoxLayout()
        info.setSpacing(5)
        title = QLabel(note["title"].strip() or "Без заголовка")
        title.setObjectName("noteTitle")
        title.setStyleSheet(f"color: {palette['foreground']};")
        title.setWordWrap(True)
        body_text = " ".join(note["body"].split())
        preview = QLabel(body_text[:130] + ("…" if len(body_text) > 130 else ""))
        if not body_text:
            preview.setText("Пустая заметка · откройте, чтобы добавить текст")
        preview.setObjectName("mutedText")
        preview.setStyleSheet(f"color: {palette['muted']};")
        preview.setWordWrap(True)
        if grid:
            preview.setMaximumHeight(54)
        tasks = note["tasks"]
        completed = sum(bool(task["completed"]) for task in tasks)
        date = self._format_date(note["updated_at"])
        meta = QLabel(
            f"{completed}/{len(tasks)} задач выполнено  ·  Изменено {date}"
            if tasks else f"Изменено {date}"
        )
        meta.setObjectName("cardMeta")
        meta.setStyleSheet(f"color: {palette['muted']};")
        info.addWidget(title)
        info.addWidget(preview)
        info.addWidget(meta)
        open_button = QPushButton("Открыть")
        open_button.setObjectName("secondaryButton")
        open_button.setStyleSheet(
            f"color: {palette['foreground']}; background: {palette['accent']}; "
            f"border: 1px solid {palette['border']}; font-weight: 700;"
        )
        open_button.clicked.connect(lambda: self.openRequested.emit(note["id"]))
        if grid:
            layout.addLayout(info, 1)
            footer = QHBoxLayout()
            footer.addStretch()
            footer.addWidget(open_button)
            layout.addLayout(footer)
        else:
            layout.addLayout(info, 1)
            layout.addWidget(open_button)
        return card

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "notes_grid_layout"):
            QTimer.singleShot(0, self._reflow_note_cards)

    def _reflow_note_cards(self):
        if self._column_count() != self._rendered_columns:
            self._render_note_cards(self._visible_notes)

    def _refresh_stats(self, notes: list[dict]):
        all_notes = self.database.list_notes()
        total_tasks = [task for note in all_notes for task in note["tasks"]]
        self.note_stat.setText(f"{len(all_notes)} заметок")
        self.task_stat.setText(
            f"{sum(not task['completed'] for task in total_tasks)} активных задач"
        )
        self.done_stat.setText(
            f"{sum(bool(task['completed']) for task in total_tasks)} выполнено"
        )
        self.subheading.setText(
            f"{len(notes)} заметок в текущем списке · "
            f"{sum(not task['completed'] for task in total_tasks)} задач впереди"
        )

    def _refresh_tasks(self):
        selected = self.task_filter.currentData() if hasattr(self, "task_filter") else "all"
        self.tasks_list.blockSignals(True)
        self.tasks_list.clear()
        for note in self.database.list_notes(status="active"):
            for task in note["tasks"]:
                completed = bool(task["completed"])
                if selected == "active" and completed:
                    continue
                if selected == "completed" and not completed:
                    continue
                item = QListWidgetItem(
                    f"{'✓' if completed else '○'}  {task['text']}    ·    "
                    f"{note['title'] or 'Без заголовка'}"
                )
                item.setData(Qt.ItemDataRole.UserRole, task["id"])
                item.setData(Qt.ItemDataRole.UserRole + 1, completed)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if completed else Qt.CheckState.Unchecked
                )
                item.setForeground(
                    Qt.GlobalColor.gray if task["completed"] else Qt.GlobalColor.white
                )
                self.tasks_list.addItem(item)
        self.tasks_list.blockSignals(False)

    def _task_item_changed(self, item: QListWidgetItem):
        try:
            self.database.update_task(
                item.data(Qt.ItemDataRole.UserRole),
                completed=int(item.checkState() == Qt.CheckState.Checked),
            )
            self.refresh()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            logger.exception("Не удалось изменить задачу")
            QMessageBox.warning(self, "Stickly", "Не удалось сохранить состояние задачи.")

    def _refresh_trash(self):
        self.trash_list.clear()
        for note in self.database.list_trash():
            item = QListWidgetItem(
                f"{note['title'] or 'Без заголовка'}  ·  "
                f"{self._format_date(note['deleted_at'])}"
            )
            item.setData(Qt.ItemDataRole.UserRole, note["id"])
            self.trash_list.addItem(item)

    def _trash_menu(self, point):
        item = self.trash_list.itemAt(point)
        if not item:
            return
        note_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        restore = menu.addAction("Восстановить")
        delete = menu.addAction("Удалить навсегда")
        action = menu.exec(self.trash_list.mapToGlobal(point))
        if action == restore:
            self.database.restore_note(note_id)
            self.refresh()
        elif action == delete:
            if QMessageBox.question(
                self, "Удалить заметку?", "Заметка и её задачи будут удалены навсегда."
            ) == QMessageBox.StandardButton.Yes:
                self.database.delete_note_permanently(note_id)
                self.refresh()

    def _note_menu(self, widget: QWidget, point, note_id: str):
        menu = QMenu(self)
        duplicate = menu.addAction("Дублировать")
        archive = menu.addAction("Переместить в архив")
        delete = menu.addAction("В корзину")
        action = menu.exec(widget.mapToGlobal(point))
        if action == duplicate:
            self.note_duplicate_requested(note_id)
        elif action == archive:
            self.note_archive_requested(note_id)
        elif action == delete:
            self.note_trash_requested(note_id)

    def set_note_actions(self, *, duplicate, archive, trash):
        self.note_duplicate_requested = duplicate
        self.note_archive_requested = archive
        self.note_trash_requested = trash

    @staticmethod
    def _format_date(value: str | None) -> str:
        if not value:
            return "недавно"
        try:
            dt = datetime.fromisoformat(value)
            return dt.astimezone().strftime("%d.%m.%Y, %H:%M")
        except (ValueError, TypeError):
            return "недавно"

    def closeEvent(self, event):
        event.ignore()
        self.closeRequested.emit()
