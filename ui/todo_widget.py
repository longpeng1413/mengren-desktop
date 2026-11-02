"""Desktop to-do list widget for the F3 desktop tools.

Unfinished items come first, numbered 1, 2, 3...; finished items follow under
their own heading, numbered again from 1, struck through and greyed. Click the
circle to finish an item, double-click its text to edit it, hover it to show
the delete button, drag it up or down to reorder it within its group, and type
in the bottom box to add one (Enter keeps the box ready for the next). A
deleted item can be restored for a few seconds. Drag the title bar to move the
list and the corner grip to change its width. Every change is saved at once.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app import todo_model
from app.reminder_preferences import ReminderSettings
from app.todo_model import TodoItem
from ui import theme
from ui.color_picker import pick_color

MIN_WIDTH = 240
MAX_WIDTH = 760
UNDO_SECONDS = 6
DRAG_DISTANCE = 6
FONT_SIZES = (("小", 13), ("中", 15), ("大", 17), ("特大", 20))

_STYLE = f"""
#todoCard {{
    background-color: rgba(21, 21, 24, 238);
    border: 1px solid {theme.LINE};
    border-radius: 12px;
}}
#todoCard QLabel {{ background: transparent; font-family: {theme.FONT}; }}
#todoHeader {{ border-bottom: 1px solid {theme.LINE}; }}
QLabel#todoTitle {{ font-weight: 700; }}
QLabel#todoCounts, QLabel#todoSection, QLabel#todoNumber, QLabel#todoEmpty {{ color: {theme.MUTED}; }}
QLabel#todoSection {{ font-size: 12px; font-weight: 600; padding-top: 6px; }}
#todoRow {{ border-radius: 6px; }}
#todoRow:hover {{ background-color: rgba(255, 255, 255, 10); }}
QPushButton#todoCheck {{
    background: transparent;
    border: 2px solid {theme.MUTED};
    border-radius: 9px;
    color: transparent;
    font-size: 11px;
    font-weight: 700;
}}
QPushButton#todoCheck:hover {{ border-color: {theme.ACCENT}; }}
QPushButton#todoCheck:checked {{
    background: {theme.ACCENT};
    border-color: {theme.ACCENT};
    color: {theme.ACCENT_INK};
}}
QPushButton#todoDelete, QPushButton#todoMenu {{
    background: transparent;
    border: none;
    color: {theme.MUTED};
    font-size: 15px;
}}
QPushButton#todoMenu {{ color: {theme.TEXT}; font-size: 18px; font-weight: 700; border-radius: 6px; }}
QPushButton#todoMenu:hover {{ background: {theme.HOVER}; }}
QPushButton#todoDelete:hover {{ color: {theme.DANGER}; }}
QPushButton#todoMenu:hover {{ color: {theme.TEXT}; }}
QPushButton#todoUndo {{
    background: transparent;
    border: 1px solid {theme.LINE};
    border-radius: 6px;
    color: {theme.ACCENT};
    padding: 2px 10px;
    font-family: {theme.FONT};
}}
QLineEdit {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    border-radius: 7px;
    padding: 5px 8px;
    font-family: {theme.FONT};
    selection-background-color: #2f5a46;
}}
QLineEdit:focus {{ border-color: {theme.ACCENT}; }}
QFrame#todoDropLine {{ background: {theme.ACCENT}; border: none; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {theme.LINE}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
""" + theme.MENU_STYLE


class _InlineEdit(QLineEdit):
    """Edits text in place: Enter or leaving saves, Esc cancels."""

    committed = Signal(str)
    cancelled = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.committed.emit(self.text())
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self.isVisible():
            self.committed.emit(self.text())


class _TodoRow(QWidget):
    """One numbered line with its circle, text and delete button."""

    toggled = Signal(str)
    delete_requested = Signal(str)
    renamed = Signal(str, str)

    def __init__(self, item: TodoItem, number: int, owner: "TodoListWidget") -> None:
        super().__init__()
        self.item = item
        self._owner = owner
        self._press: QPoint | None = None
        self._dragging = False
        self.setObjectName("todoRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self.number = QLabel(f"{number}.")
        self.number.setObjectName("todoNumber")
        self.number.setFixedWidth(26)
        self.number.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.check = QPushButton("✓")
        self.check.setObjectName("todoCheck")
        self.check.setCheckable(True)
        self.check.setChecked(item.done)
        self.check.setFixedSize(18, 18)
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check.setToolTip("标记为未完成" if item.done else "标记为完成")
        self.check.clicked.connect(lambda: self.toggled.emit(self.item.item_id))
        self.text = QLabel(item.text)
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.editor = _InlineEdit()
        self.editor.hide()
        self.editor.committed.connect(self._commit)
        self.editor.cancelled.connect(self._cancel)
        self.delete = QPushButton("×")
        self.delete.setObjectName("todoDelete")
        self.delete.setFixedSize(22, 22)
        self.delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete.setToolTip("删除这一条")
        self.delete.clicked.connect(lambda: self.delete_requested.emit(self.item.item_id))
        policy = self.delete.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.delete.setSizePolicy(policy)
        self.delete.hide()
        for label in (self.number, self.text):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 2, 4)
        layout.setSpacing(8)
        layout.addWidget(self.number, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.delete, 0, Qt.AlignmentFlag.AlignTop)

    def apply_style(self, color: QColor, font_size: int) -> None:
        font = QFont(self.text.font())
        font.setPixelSize(font_size)
        font.setStrikeOut(self.item.done)
        self.text.setFont(font)
        self.editor.setFont(font)
        shown = QColor(theme.MUTED) if self.item.done else color
        self.text.setStyleSheet(f"color: {shown.name()};")
        number_font = QFont(font)
        number_font.setStrikeOut(False)
        number_font.setPixelSize(max(11, font_size - 2))
        self.number.setFont(number_font)

    @property
    def editing(self) -> bool:
        return self.editor.isVisible()

    def begin_edit(self) -> None:
        self.text.hide()
        self.editor.setText(self.item.text)
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()

    def _commit(self, text: str) -> None:
        if not self.editor.isVisible():
            return
        self.editor.hide()
        self.text.show()
        if todo_model.clean_text(text) and todo_model.clean_text(text) != self.item.text:
            self.renamed.emit(self.item.item_id, text)

    def _cancel(self) -> None:
        self.editor.hide()
        self.text.show()

    def enterEvent(self, event) -> None:
        self.delete.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.delete.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.editing:
            self._press = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        position = event.globalPosition().toPoint()
        if not self._dragging and (position - self._press).manhattanLength() >= DRAG_DISTANCE:
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._owner.begin_row_drag(self)
        if self._dragging:
            self._owner.continue_row_drag(self, position)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            self._press = None
            if self._dragging:
                self._dragging = False
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self._owner.finish_row_drag(self)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.begin_edit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        self._owner.open_menu(event.globalPos(), self)


class _WidthGrip(QLabel):
    """Corner handle that changes the list's width."""

    def __init__(self, owner: "TodoListWidget") -> None:
        super().__init__("◢")
        self._owner = owner
        self._start: QPoint | None = None
        self._start_width = 0
        self.setObjectName("todoNumber")
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("拖动调整宽度")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.globalPosition().toPoint()
            self._start_width = self._owner.width()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            delta = event.globalPosition().toPoint().x() - self._start.x()
            self._owner.set_list_width(self._start_width + delta)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._start = None
            self._owner.width_changed.emit(self._owner.width())
            event.accept()


class TodoListWidget(QWidget):
    """A desktop to-do list card kept with the other desktop widgets."""

    position_saved = Signal(QPoint)
    items_changed = Signal(object)
    title_changed = Signal(str)
    appearance_changed = Signal(str, int)
    width_changed = Signal(int)
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = ReminderSettings(kind="todo")
        self._items: tuple[TodoItem, ...] = ()
        self._rows: list[_TodoRow] = []
        self._drag_offset: QPoint | None = None
        self._row_drag_target = -1
        self._last_removed: tuple[TodoItem, int] | None = None
        self.setObjectName("todoList")
        self.setWindowTitle("待办清单")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(_STYLE)

        card = QFrame()
        card.setObjectName("todoCard")
        header = QWidget()
        header.setObjectName("todoHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        header.setCursor(Qt.CursorShape.SizeAllCursor)
        header.setToolTip("按住标题栏拖动")
        self._header = header
        self.title = QLabel()
        self.title.setObjectName("todoTitle")
        self.title_editor = _InlineEdit()
        self.title_editor.hide()
        self.title_editor.committed.connect(self._commit_title)
        self.title_editor.cancelled.connect(self._cancel_title)
        self.counts = QLabel()
        self.counts.setObjectName("todoCounts")
        self.menu_button = QPushButton("⋯")
        self.menu_button.setObjectName("todoMenu")
        self.menu_button.setFixedSize(30, 26)
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_button.setToolTip("更多操作")
        self.menu_button.clicked.connect(
            lambda: self.open_menu(self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height())))
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 8, 8)
        header_layout.setSpacing(8)
        header_layout.addWidget(self.title)
        header_layout.addWidget(self.title_editor, 1)
        header_layout.addStretch()
        header_layout.addWidget(self.counts)
        header_layout.addWidget(self.menu_button)
        for widget in (header, self.title, self.counts):
            widget.installEventFilter(self)

        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(6, 4, 8, 4)
        self._list_layout.setSpacing(1)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._list)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._drop_line = QFrame(self._list)
        self._drop_line.setObjectName("todoDropLine")
        self._drop_line.setFixedHeight(2)
        self._drop_line.hide()

        self.undo_label = QLabel()
        self.undo_label.setObjectName("todoCounts")
        self.undo_button = QPushButton("撤销")
        self.undo_button.setObjectName("todoUndo")
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.undo_button.clicked.connect(self.undo_delete)
        self._undo_bar = QWidget()
        undo_layout = QHBoxLayout(self._undo_bar)
        undo_layout.setContentsMargins(14, 0, 12, 0)
        undo_layout.addWidget(self.undo_label, 1)
        undo_layout.addWidget(self.undo_button)
        self._undo_bar.hide()
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.setInterval(UNDO_SECONDS * 1000)
        self._undo_timer.timeout.connect(self._hide_undo)

        self.input = QLineEdit()
        self.input.setPlaceholderText("＋ 添加待办，按回车确认")
        self.input.setMaxLength(todo_model.MAX_TEXT_LENGTH)
        self.input.returnPressed.connect(self._add_from_input)
        grip = _WidthGrip(self)
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 4, 6, 10)
        footer.setSpacing(6)
        footer.addWidget(self.input, 1)
        footer.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(4)
        card_layout.addWidget(header)
        card_layout.addWidget(self._scroll)
        card_layout.addWidget(self._undo_bar)
        card_layout.addLayout(footer)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

    # ------------------------------------------------- manager interface ----

    @property
    def items(self) -> tuple[TodoItem, ...]:
        return self._items

    @property
    def is_dragging(self) -> bool:
        """Moving the card or a row, or typing: keep it out of the desktop layer."""
        typing = self.isActiveWindow() and isinstance(QGuiApplication.focusObject(), QLineEdit)
        return self._drag_offset is not None or self._row_drag_target >= 0 or typing

    def set_settings(self, settings: ReminderSettings) -> None:
        self._settings = settings
        self._items = todo_model.display_order(settings.todo_items)
        self.title.setText(settings.todo_title)
        self.set_list_width(settings.text_width, resize_only=True)
        self._rebuild()

    def set_always_on_top(self, enabled: bool) -> None:
        flag = Qt.WindowType.WindowStaysOnTopHint
        if bool(self.windowFlags() & flag) == enabled:
            return
        was_visible = self.isVisible()
        position = QPoint(self.pos())
        self.setWindowFlag(flag, enabled)
        self.move(position)
        if was_visible:
            self.show()
            if enabled:
                self.raise_()

    def focus_input(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    # ------------------------------------------------------ list content ----

    def _color(self) -> QColor:
        color = QColor(self._settings.text_color)
        return color if color.isValid() else QColor(theme.TEXT)

    def _font_size(self) -> int:
        return max(11, min(28, self._settings.font_size))

    def _rebuild(self) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows = []
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._drop_line:
                widget.deleteLater()

        size = self._font_size()
        title_font = QFont(self.title.font())
        title_font.setPixelSize(size + 2)
        self.title.setFont(title_font)
        self.title.setStyleSheet(f"color: {self._color().name()};")
        self.title_editor.setFont(title_font)
        open_count, done_count = todo_model.counts(self._items)
        self.counts.setText(f"未完成 {open_count} · 已完成 {done_count}")
        self.input.setFont(self._small_font(size))

        if not self._items:
            empty = QLabel("还没有待办，在下方输入后按回车添加。")
            empty.setObjectName("todoEmpty")
            empty.setWordWrap(True)
            empty.setFont(self._small_font(size))
            empty.setContentsMargins(8, 10, 8, 10)
            self._list_layout.addWidget(empty)
        unfinished = todo_model.unfinished(self._items)
        finished = todo_model.finished(self._items)
        for number, item in enumerate(unfinished, start=1):
            self._add_row(item, number)
        if finished:
            section = QLabel(f"已完成 {len(finished)}")
            section.setObjectName("todoSection")
            section.setContentsMargins(8, 0, 0, 0)
            self._list_layout.addWidget(section)
        for number, item in enumerate(finished, start=1):
            self._add_row(item, number)
        self._fit_height()

    def _small_font(self, size: int) -> QFont:
        font = QFont(self.font())
        font.setFamily("Microsoft YaHei UI")
        font.setPixelSize(max(11, size - 1))
        return font

    def _add_row(self, item: TodoItem, number: int) -> None:
        row = _TodoRow(item, number, self)
        row.apply_style(self._color(), self._font_size())
        row.toggled.connect(self.toggle_item)
        row.delete_requested.connect(self.delete_item)
        row.renamed.connect(self.rename_item)
        self._list_layout.addWidget(row)
        self._rows.append(row)

    def _fit_height(self) -> None:
        """Grow with the list up to most of the screen, then scroll."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        limit = int(screen.availableGeometry().height() * 0.6) if screen else 520
        # The list fills the card's width minus its 1-pixel border on each side.
        width = max(1, self.width() - 2)
        self._list_layout.activate()
        content = self._list_layout.totalHeightForWidth(width)
        if content < 0:
            content = self._list.sizeHint().height()
        self._scroll.setFixedHeight(max(48, min(content + 4, limit)))
        self.adjustSize()

    def set_list_width(self, width: int, resize_only: bool = False) -> None:
        width = max(MIN_WIDTH, min(MAX_WIDTH, int(width)))
        self.setFixedWidth(width)
        if not resize_only:
            self._fit_height()

    def _change(self, items: tuple[TodoItem, ...]) -> None:
        self._items = items
        self._rebuild()
        self.items_changed.emit(items)

    # ----------------------------------------------------------- actions ----

    def add_item(self, text: str) -> None:
        updated = todo_model.add(self._items, text)
        if updated != self._items:
            self._change(updated)

    def _add_from_input(self) -> None:
        self.add_item(self.input.text())
        self.input.clear()
        self.input.setFocus()

    def toggle_item(self, item_id: str) -> None:
        self._change(todo_model.toggle(self._items, item_id))

    def rename_item(self, item_id: str, text: str) -> None:
        self._change(todo_model.rename(self._items, item_id, text))

    def delete_item(self, item_id: str) -> None:
        items, removed, index = todo_model.remove(self._items, item_id)
        if removed is None:
            return
        self._last_removed = (removed, index)
        text = removed.text if len(removed.text) <= 18 else removed.text[:18] + "…"
        self.undo_label.setText(f"已删除：{text}")
        self._undo_bar.show()
        self._undo_timer.start()
        self._change(items)

    def undo_delete(self) -> None:
        if self._last_removed is None:
            return
        item, index = self._last_removed
        self._hide_undo()
        self._change(todo_model.restore(self._items, item, index))

    def _hide_undo(self) -> None:
        self._last_removed = None
        self._undo_timer.stop()
        self._undo_bar.hide()
        self._fit_height()

    def clear_finished(self) -> None:
        self._change(todo_model.clear_finished(self._items))

    def finish_all(self) -> None:
        self._change(todo_model.finish_all(self._items))

    # ----------------------------------------------------- row dragging ----

    def _group_rows(self, row: _TodoRow) -> list[_TodoRow]:
        return [other for other in self._rows if other.item.done == row.item.done]

    def begin_row_drag(self, row: _TodoRow) -> None:
        self._row_drag_target = self._group_rows(row).index(row)

    def continue_row_drag(self, row: _TodoRow, global_position: QPoint) -> None:
        group = self._group_rows(row)
        y = self._list.mapFromGlobal(global_position).y()
        target = len(group)
        for index, other in enumerate(group):
            if y < other.geometry().center().y():
                target = index
                break
        self._row_drag_target = target
        if target < len(group):
            line_y = group[target].geometry().top() - 1
        else:
            line_y = group[-1].geometry().bottom() + 1
        self._drop_line.setGeometry(8, max(0, line_y), self._list.width() - 16, 2)
        self._drop_line.show()
        self._drop_line.raise_()
        self._scroll.ensureVisible(0, y, 0, 20)

    def finish_row_drag(self, row: _TodoRow) -> None:
        group = self._group_rows(row)
        current = group.index(row)
        target = self._row_drag_target
        self._row_drag_target = -1
        self._drop_line.hide()
        if target < 0:
            return
        # Dropping below the row itself means one place earlier once it is lifted out.
        position = target - 1 if target > current else target
        if position != current:
            self._change(todo_model.move(self._items, row.item.item_id, position))

    # -------------------------------------------------------------- menu ----

    def open_menu(self, global_position: QPoint, row: _TodoRow | None = None) -> None:
        menu = QMenu(self)
        edit_action = delete_action = None
        if row is not None:
            edit_action = menu.addAction("修改这一条")
            delete_action = menu.addAction("删除这一条")
            menu.addSeparator()
        title_action = menu.addAction("修改标题")
        _open_count, done_count = todo_model.counts(self._items)
        clear_action = menu.addAction(f"清除已完成（{done_count}）")
        clear_action.setEnabled(done_count > 0)
        finish_action = menu.addAction("全部标为完成")
        finish_action.setEnabled(any(not item.done for item in self._items))
        menu.addSeparator()
        size_menu = menu.addMenu("字号")
        size_actions = {}
        for label, size in FONT_SIZES:
            action = size_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(size == self._font_size())
            size_actions[action] = size
        color_action = menu.addAction("文字颜色…")
        menu.addSeparator()
        remove_action = menu.addAction("删除整个清单")
        selected = menu.exec(global_position)
        if selected is None:
            return
        if selected == edit_action and row is not None:
            row.begin_edit()
        elif selected == delete_action and row is not None:
            self.delete_item(row.item.item_id)
        elif selected == title_action:
            self.begin_title_edit()
        elif selected == clear_action:
            self.clear_finished()
        elif selected == finish_action:
            self.finish_all()
        elif selected in size_actions:
            self.appearance_changed.emit(self._settings.text_color, size_actions[selected])
        elif selected == color_action:
            color = pick_color(self._color(), self, "选择待办文字颜色")
            if color.isValid():
                self.appearance_changed.emit(color.name(), self._font_size())
        elif selected == remove_action:
            self.delete_requested.emit()

    def contextMenuEvent(self, event) -> None:
        self.open_menu(event.globalPos())

    # ------------------------------------------------------------- title ----

    def begin_title_edit(self) -> None:
        self.title.hide()
        self.title_editor.setText(self.title.text())
        self.title_editor.show()
        self.title_editor.setFocus()
        self.title_editor.selectAll()

    def _commit_title(self, text: str) -> None:
        if not self.title_editor.isVisible():
            return
        self.title_editor.hide()
        self.title.show()
        cleaned = todo_model.clean_text(text)[:60]
        if cleaned and cleaned != self.title.text():
            self.title.setText(cleaned)
            self.title_changed.emit(cleaned)

    def _cancel_title(self) -> None:
        self.title_editor.hide()
        self.title.show()

    # ------------------------------------------------- moving the card ----

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            return True
        if kind == QEvent.Type.MouseMove and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return True
        if kind == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
            self._drag_offset = None
            self.position_saved.emit(self.pos())
            return True
        if kind == QEvent.Type.MouseButtonDblClick and watched is self.title:
            self._drag_offset = None
            self.begin_title_edit()
            return True
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), super().sizeHint().height())

