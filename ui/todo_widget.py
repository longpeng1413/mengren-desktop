"""Desktop to-do list widget for the F3 desktop tools.

Closed, the list is only a pull cord on the desktop: drag its hook to move it,
click or pull its knob down to open the list, which then hangs from the hook
and shows everything; click the hook or "收起" to hide it again.

Unfinished items come first, numbered 1, 2, 3...; finished items follow under
their own heading, numbered again from 1, struck through and greyed. Click the
circle to finish an item, double-click its text to edit it, hover it to show
the delete button, drag it up or down to reorder it within its group, and type
in the bottom box to add one (Enter keeps the box ready for the next). A
deleted item can be restored for a few seconds. Drag the title bar to move the
list and the corner grip to change its width. Every change is saved at once.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from math import ceil

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app import todo_model
from app.reminder_preferences import TODO_COLUMN_CHOICES, TODO_COLUMNS_AFTER, TODO_CORD_STYLES
from app.reminder_preferences import TODO_CORD_STYLE as TODO_CORD
from app.reminder_preferences import TODO_BACKGROUND as TODO_BACK
from app.reminder_preferences import TODO_OPACITY as TODO_ALPHA
from app.reminder_preferences import TODO_TEXT_COLOR as TODO_TEXT
from app.reminder_preferences import ReminderSettings
from app.todo_model import TodoItem, TrashedItem
from ui import pull_cord_art, theme
from ui.color_picker import pick_color

MIN_WIDTH = 240
MAX_WIDTH = 760
UNDO_SECONDS = 6
DRAG_DISTANCE = 6
FONT_SIZES = (("小", 13), ("中", 15), ("大", 17), ("特大", 20))

DONE_GREEN = "#4cc38a"


@dataclass(frozen=True, slots=True)
class TodoPalette:
    """Colours of one list, derived from its text and background choices."""

    text: str
    muted: str
    line: str
    hover: str
    field: str
    card: str


def palette_for(text: str, background: str, opacity: int) -> TodoPalette:
    """Pick readable helper colours for a light or a dark background."""
    back = QColor(background)
    if not back.isValid():
        back = QColor("#ffffff")
    alpha = round(max(5, min(100, opacity)) * 2.55)
    card = f"rgba({back.red()}, {back.green()}, {back.blue()}, {alpha})"
    if back.lightnessF() >= 0.55:
        return TodoPalette(text, "#6b6b6b", "rgba(0, 0, 0, 38)", "rgba(0, 0, 0, 14)", "rgba(255, 255, 255, 190)", card)
    return TodoPalette(text, theme.MUTED, theme.LINE, "rgba(255, 255, 255, 14)", "rgba(28, 28, 33, 210)", card)


def style_for(palette: TodoPalette) -> str:
    return f"""
#todoCard {{
    background-color: {palette.card};
    border: 1px solid {palette.line};
    border-radius: 12px;
}}
#todoCard QLabel {{ background: transparent; font-family: {theme.FONT}; }}
#todoHeader {{ border-bottom: 1px solid {palette.line}; }}
QLabel#todoTitle {{ font-weight: 700; }}
QLabel#todoCounts, QLabel#todoSection, QLabel#todoNumber, QLabel#todoEmpty {{ color: {palette.muted}; }}
QLabel#todoCounts {{ font-size: 11px; }}
QLabel#todoSection {{ font-size: 12px; font-weight: 600; padding-top: 6px; }}
#todoRow {{ border-radius: 6px; }}
#todoRow:hover {{ background-color: {palette.hover}; }}
QPushButton#todoCheck {{
    background: transparent;
    border: 2px solid {palette.muted};
    border-radius: 3px;
    color: transparent;
    font-size: 11px;
    font-weight: 800;
    padding: 0px;
}}
QPushButton#todoCheck:hover {{ border-color: {DONE_GREEN}; }}
QPushButton#todoCheck:checked {{
    background: {DONE_GREEN};
    border-color: {DONE_GREEN};
    color: #ffffff;
}}
QPushButton#todoDelete, QPushButton#todoMenu {{
    background: transparent;
    border: none;
    color: {palette.muted};
    font-size: 15px;
}}
QPushButton#todoMenu {{ color: {palette.text}; font-family: {theme.FONT}; font-size: 13px; font-weight: 600; border-radius: 6px; }}
QPushButton#todoMenu:hover {{ background: {palette.hover}; }}
QPushButton#todoDelete:hover {{ color: {theme.DANGER}; }}
QPushButton#todoUndo {{
    background: transparent;
    border: 1px solid {palette.line};
    border-radius: 6px;
    color: {DONE_GREEN};
    padding: 2px 10px;
    font-family: {theme.FONT};
}}
QLineEdit {{
    color: {palette.text};
    background: {palette.field};
    border: 1px solid {palette.line};
    border-radius: 7px;
    padding: 5px 8px;
    font-family: {theme.FONT};
    selection-background-color: #2f5a46;
}}
QLineEdit:focus {{ border-color: {DONE_GREEN}; }}
QFrame#todoDropLine {{ background: {DONE_GREEN}; border: none; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {palette.line}; border-radius: 3px; min-height: 24px; }}
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
    """One numbered line with its check box, text and delete button."""

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
        self.check.setFixedSize(16, 16)
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
        # Two pixels above and below each line: half the earlier gap between items.
        layout.setContentsMargins(4, 2, 2, 2)
        layout.setSpacing(8)
        layout.addWidget(self.number, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.delete, 0, Qt.AlignmentFlag.AlignTop)

    def apply_style(self, color: QColor, font_size: int, muted: str) -> None:
        font = QFont(self.text.font())
        font.setPixelSize(font_size)
        font.setStrikeOut(self.item.done)
        self.text.setFont(font)
        self.editor.setFont(font)
        shown = QColor(muted) if self.item.done else color
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
            self._start_width = self._owner.base_width
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            delta = event.globalPosition().toPoint().x() - self._start.x()
            # Two columns share the extra width, so each column grows by half.
            self._owner.set_list_width(self._start_width + delta // self._owner.column_count)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._start = None
            self._owner.width_changed.emit(self._owner.base_width)
            event.accept()


class _PullCord(QWidget):
    """The cord the list hangs from: hook to move, knob to click or pull open."""

    toggle_requested = Signal()
    open_requested = Signal()

    HOOK = pull_cord_art.MOUNT_HEIGHT
    STRING = 10
    PULL_LIMIT = 90
    PULL_TO_OPEN = 28

    def __init__(self, owner: "TodoListWidget") -> None:
        super().__init__(owner)
        self._owner = owner
        self.collapsed = True
        self.pull = 0
        self._press: QPoint | None = None
        self._start_position = QPoint()
        self._mode = ""
        self._moved = False
        self._count = 0
        self.style = pull_cord_art.style(TODO_CORD)
        self.setFixedWidth(self.style.width)
        self._resize()

    @property
    def busy(self) -> bool:
        return self._press is not None

    def set_state(self, collapsed: bool, open_count: int, style_key: str) -> None:
        self.collapsed = collapsed
        self._count = open_count
        self.style = pull_cord_art.style(style_key)
        self.setFixedWidth(self.style.width)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "点一下或按住往下拉，打开待办；按住顶部挂钩拖动可移动位置"
            if collapsed
            else "点挂钩收起待办；按住挂钩拖动可移动位置"
        )
        self._resize()
        self.update()

    def _resize(self) -> None:
        if self.collapsed:
            self.setFixedHeight(self.HOOK + self.STRING + self.pull + self.style.knob_height)
        else:
            self.setFixedHeight(self.HOOK + 10)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Almost invisible, but it keeps clicks on the cord from falling through.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        center = self.width() / 2
        knob_top = self.height() - (self.style.knob_height if self.collapsed else 0)
        if self.collapsed:
            area = QRectF(0, knob_top, self.width(), self.style.knob_height)
            self.style.draw_knob(painter, area, self._count)
            end = knob_top + self.style.attach
        else:
            end = knob_top + 2
        pull_cord_art.draw_string(painter, center, 12, end, self.style.string_width)
        pull_cord_art.draw_mount(painter, center)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._press = event.globalPosition().toPoint()
        self._start_position = QPoint(self._owner.pos())
        self._moved = False
        on_hook = event.position().y() <= self.HOOK + 4 or not self.collapsed
        self._mode = "hook" if on_hook else "knob"
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None:
            super().mouseMoveEvent(event)
            return
        delta = event.globalPosition().toPoint() - self._press
        if delta.manhattanLength() >= DRAG_DISTANCE:
            self._moved = True
        if self._mode == "hook" and self._moved:
            self._owner.move(self._start_position + delta)
        elif self._mode == "knob":
            self.pull = max(0, min(self.PULL_LIMIT, delta.y()))
            self._resize()
            self._owner.adjustSize()
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            super().mouseReleaseEvent(event)
            return
        mode, moved, pulled = self._mode, self._moved, self.pull
        self._press = None
        self.pull = 0
        self._resize()
        self._owner.adjustSize()
        if mode == "hook":
            if moved:
                self._owner.position_saved.emit(self._owner.pos())
            else:
                self.toggle_requested.emit()
        elif pulled >= self.PULL_TO_OPEN or not moved:
            self.open_requested.emit()
        event.accept()


class _GroupBlock(QWidget):
    """One group of rows (unfinished or finished) in one or two columns."""

    SPACING = 12

    def __init__(self, columns: int) -> None:
        super().__init__()
        self.columns: list[list["_TodoRow"]] = [[] for _ in range(columns)]
        self._layouts: list[QVBoxLayout] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.SPACING)
        for _ in range(columns):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(1)
            column_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            layout.addWidget(column, 1)
            self._layouts.append(column_layout)

    def add(self, row: "_TodoRow", column: int) -> None:
        self.columns[column].append(row)
        self._layouts[column].addWidget(row)

    def measure(self, width: int) -> int:
        """Height of the taller column at ``width``."""
        count = len(self.columns)
        column_width = max(1, (width - self.SPACING * (count - 1)) // count)
        tallest = 0
        for rows in self.columns:
            height = 0
            for row in rows:
                row.ensurePolished()
                line = row.heightForWidth(column_width) if row.hasHeightForWidth() else -1
                height += line if line >= 0 else row.sizeHint().height()
            height += max(0, len(rows) - 1)
            tallest = max(tallest, height)
        return tallest


class TodoListWidget(QWidget):
    """A desktop to-do list card kept with the other desktop widgets."""

    position_saved = Signal(QPoint)
    items_changed = Signal(object)
    title_changed = Signal(str)
    appearance_changed = Signal(str, str, int, int, int, str)
    width_changed = Signal(int)
    collapsed_changed = Signal(bool)
    trash_changed = Signal(object)
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = ReminderSettings(kind="todo")
        self._items: tuple[TodoItem, ...] = ()
        self._rows: list[_TodoRow] = []
        self._drag_offset: QPoint | None = None
        self._row_drag_target = -1
        self._last_removed: tuple[TodoItem, int] | None = None
        self._collapsed = True
        self._trash: tuple[TrashedItem, ...] = ()
        self._base_width = 340
        self._two_columns = False
        self.setObjectName("todoList")
        self.setWindowTitle("待办清单")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._palette = palette_for(TODO_TEXT, TODO_BACK, TODO_ALPHA)
        self.setStyleSheet(style_for(self._palette))

        card = QFrame()
        card.setObjectName("todoCard")
        self._card = card
        self.cord = _PullCord(self)
        self.cord.open_requested.connect(self.expand)
        self.cord.toggle_requested.connect(self.toggle_collapsed)
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
        self.style_button = QPushButton("外观")
        self.style_button.setObjectName("todoMenu")
        self.style_button.setFixedSize(40, 26)
        self.style_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.style_button.setToolTip("外观设置：文字颜色、背景颜色、透明度、字号")
        self.style_button.clicked.connect(self.open_appearance)
        self.hide_button = QPushButton("收起")
        self.hide_button.setObjectName("todoMenu")
        self.hide_button.setFixedSize(40, 26)
        self.hide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide_button.setToolTip("收起成拉绳")
        self.hide_button.clicked.connect(self.collapse)
        self.menu_button = QPushButton("⋯")
        self.menu_button.setObjectName("todoMenu")
        self.menu_button.setFixedSize(30, 26)
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_button.setToolTip("更多操作")
        self.menu_button.clicked.connect(
            lambda: self.open_menu(self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height())))
        )
        self.trash_button = QPushButton("回收站")
        self.trash_button.setObjectName("todoMenu")
        self.trash_button.setFixedHeight(26)
        self.trash_button.setMinimumWidth(52)
        self.trash_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trash_button.setToolTip("最近删除的待办：可以还原，也可以彻底删除")
        self.trash_button.clicked.connect(self.open_trash)
        title_row = QHBoxLayout()
        title_row.setSpacing(0)
        title_row.addWidget(self.title)
        title_row.addWidget(self.title_editor, 1)
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addLayout(title_row)
        names.addWidget(self.counts)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 8, 7)
        header_layout.setSpacing(4)
        header_layout.addLayout(names)
        header_layout.addStretch()
        for button in (self.style_button, self.trash_button, self.hide_button, self.menu_button):
            header_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
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
        outer.setSpacing(0)
        outer.addWidget(self.cord, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        outer.addWidget(card)
        outer.addStretch()

    # ------------------------------------------------- manager interface ----

    @property
    def items(self) -> tuple[TodoItem, ...]:
        return self._items

    @property
    def is_dragging(self) -> bool:
        """Moving the card or a row, or typing: keep it out of the desktop layer."""
        typing = self.isActiveWindow() and isinstance(QGuiApplication.focusObject(), QLineEdit)
        return (
            self._drag_offset is not None
            or self._row_drag_target >= 0
            or self.cord.busy
            or typing
        )

    def set_settings(self, settings: ReminderSettings) -> None:
        self._settings = settings
        self._palette = palette_for(
            self._color().name(), settings.todo_background, settings.todo_opacity
        )
        self.setStyleSheet(style_for(self._palette))
        self._items = todo_model.display_order(settings.todo_items)
        self._trash = tuple(settings.todo_trash)
        self.title.setText(settings.todo_title)
        self._base_width = max(MIN_WIDTH, min(MAX_WIDTH, int(settings.text_width)))
        self._collapsed = settings.todo_collapsed
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

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def expand(self) -> None:
        if self._collapsed:
            self._set_collapsed(False)

    def collapse(self) -> None:
        if not self._collapsed:
            self._set_collapsed(True)

    def toggle_collapsed(self) -> None:
        self._set_collapsed(not self._collapsed)

    def _set_collapsed(self, collapsed: bool) -> None:
        """Open or close while the hook stays where it is on the desktop."""
        # The cord is always centred at the top of the window, so the hook is
        # the window's top centre. Reading the cord's position instead picked up
        # a moment when the cord sat lower, and each close moved the list down.
        hook = QPoint(self.x() + self.width() // 2, self.y())
        self._collapsed = collapsed
        self._apply_state()
        position = QPoint(hook.x() - self.width() // 2, hook.y())
        screen = QGuiApplication.screenAt(hook) or self.screen()
        if screen is not None:
            bounds = screen.availableGeometry()
            position.setX(max(bounds.left(), min(position.x(), bounds.right() - self.width() + 1)))
        self.move(position)
        self.position_saved.emit(self.pos())
        self.collapsed_changed.emit(collapsed)

    def _apply_state(self) -> None:
        open_count, _done = todo_model.counts(self._items)
        self.cord.set_state(self._collapsed, open_count, self._settings.todo_cord_style)
        self._card.setVisible(not self._collapsed)
        if self._collapsed:
            self.setFixedWidth(self.cord.width())
            self.layout().activate()
            self.resize(self.cord.width(), self.cord.height())
            self.adjustSize()
        else:
            self._apply_width()
            self._fit_height()

    def focus_input(self) -> None:
        self.expand()
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
        self.trash_button.setText(f"回收站 {len(self._trash)}" if self._trash else "回收站")
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
        self._two_columns = False
        if unfinished:
            self._add_group(unfinished)
        if finished:
            section = QLabel(f"已完成 {len(finished)}")
            section.setObjectName("todoSection")
            section.setContentsMargins(8, 0, 0, 0)
            self._list_layout.addWidget(section)
            self._add_group(finished)
        self._apply_state()

    def _add_group(self, items: tuple[TodoItem, ...]) -> None:
        """Lay one group out in two columns once it has more than the set number."""
        after = self._settings.todo_columns_after
        columns = 2 if after and len(items) > after else 1
        self._two_columns = self._two_columns or columns == 2
        group = _GroupBlock(columns)
        per_column = ceil(len(items) / columns)
        for index, item in enumerate(items):
            group.add(self._make_row(item, index + 1), index // per_column)
        self._list_layout.addWidget(group)

    def _small_font(self, size: int) -> QFont:
        font = QFont(self.font())
        font.setFamily("Microsoft YaHei UI")
        font.setPixelSize(max(11, size - 1))
        return font

    def _make_row(self, item: TodoItem, number: int) -> _TodoRow:
        row = _TodoRow(item, number, self)
        row.apply_style(self._color(), self._font_size(), self._palette.muted)
        row.toggled.connect(self.toggle_item)
        row.delete_requested.connect(self.delete_item)
        row.renamed.connect(self.rename_item)
        self._rows.append(row)
        return row

    def _content_height(self, width: int) -> int:
        """The list's full height at ``width``, counting every line."""
        layout = self._list_layout
        margins = layout.contentsMargins()
        inner = max(1, width - margins.left() - margins.right())
        total = margins.top() + margins.bottom()
        count = 0
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            # Skip only what was hidden on purpose (such as the undo bar). Lines
            # just rebuilt count as hidden until Qt shows them; skipping those
            # shrank the list to one line after ticking a box.
            if widget is None or (
                widget.isHidden() and widget.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
            ):
                continue
            if isinstance(widget, _GroupBlock):
                total += widget.measure(inner)
                count += 1
                continue
            widget.ensurePolished()
            height = widget.heightForWidth(inner) if widget.hasHeightForWidth() else -1
            if height < 0:
                height = widget.sizeHint().height()
            total += height
            count += 1
        return total + layout.spacing() * max(0, count - 1)

    def _fit_height(self) -> None:
        """Show every line; scroll only beyond most of the screen's height."""
        if self._collapsed:
            self.adjustSize()
            return
        screen = self.screen() or QGuiApplication.primaryScreen()
        limit = int(screen.availableGeometry().height() * 0.75) if screen else 600
        # The list fills the card's width minus its 1-pixel border on each side.
        content = self._content_height(max(1, self.width() - 2))
        self._scroll.setFixedHeight(max(40, min(content + 2, limit)))
        self.adjustSize()

    def showEvent(self, event) -> None:
        """Lines only know their final height once shown, so measure again."""
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_height)

    @property
    def base_width(self) -> int:
        """Width of one column, as saved in the settings."""
        return self._base_width

    @property
    def column_count(self) -> int:
        return 2 if self._two_columns else 1

    def set_list_width(self, width: int, resize_only: bool = False) -> None:
        self._base_width = max(MIN_WIDTH, min(MAX_WIDTH, int(width)))
        self._apply_width()
        if not resize_only:
            self._fit_height()

    def _apply_width(self) -> None:
        width = self._base_width
        if self._two_columns:
            width = width * 2 + _GroupBlock.SPACING
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is not None:
                width = min(width, int(screen.availableGeometry().width() * 0.92))
        self.setFixedWidth(width)

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

    @property
    def trash(self) -> tuple[TrashedItem, ...]:
        return self._trash

    def _set_trash(self, trash: tuple[TrashedItem, ...]) -> None:
        self._trash = trash
        self.trash_button.setText(f"回收站 {len(trash)}" if trash else "回收站")
        self.trash_changed.emit(trash)

    def delete_item(self, item_id: str) -> None:
        items, removed, index = todo_model.remove(self._items, item_id)
        if removed is None:
            return
        self._set_trash(todo_model.throw_away(self._trash, (removed,)))
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
        self._set_trash(todo_model.forget(self._trash, item.item_id))
        self._change(todo_model.restore(self._items, item, index))

    def _hide_undo(self) -> None:
        self._last_removed = None
        self._undo_timer.stop()
        self._undo_bar.hide()
        self._fit_height()

    def clear_finished(self) -> None:
        done = todo_model.finished(self._items)
        if done:
            self._set_trash(todo_model.throw_away(self._trash, done))
        self._change(todo_model.clear_finished(self._items))

    def restore_from_trash(self, item_ids: set[str]) -> None:
        items, trash = todo_model.restore_from_trash(self._items, self._trash, item_ids)
        self._set_trash(trash)
        self._change(items)

    def purge_from_trash(self, item_ids: set[str]) -> None:
        self._set_trash(todo_model.purge(self._trash, item_ids))

    def open_trash(self) -> None:
        dialog = TodoTrashDialog(self._trash, self)
        dialog.restore_requested.connect(self.restore_from_trash)
        dialog.purge_requested.connect(self.purge_from_trash)
        self.trash_changed.connect(dialog.set_trash)
        try:
            dialog.exec()
        finally:
            self.trash_changed.disconnect(dialog.set_trash)

    def finish_all(self) -> None:
        self._change(todo_model.finish_all(self._items))

    # ----------------------------------------------------- row dragging ----

    def _group_rows(self, row: _TodoRow) -> list[_TodoRow]:
        return [other for other in self._rows if other.item.done == row.item.done]

    def begin_row_drag(self, row: _TodoRow) -> None:
        self._row_drag_target = self._group_rows(row).index(row)

    def continue_row_drag(self, row: _TodoRow, global_position: QPoint) -> None:
        """Insert before or after the nearest line of the same group, in either column."""
        group = self._group_rows(row)
        point = self._list.mapFromGlobal(global_position)
        nearest = None
        for index, other in enumerate(group):
            rect = QRect(other.mapTo(self._list, QPoint(0, 0)), other.size())
            dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
            dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
            distance = dx * dx + dy * dy
            if nearest is None or distance < nearest[0]:
                nearest = (distance, index, rect)
        if nearest is None:
            return
        _distance, index, rect = nearest
        below = point.y() > rect.center().y()
        self._row_drag_target = index + 1 if below else index
        line_y = rect.bottom() + 1 if below else rect.top() - 1
        self._drop_line.setGeometry(rect.left() + 4, max(0, line_y), rect.width() - 8, 2)
        self._drop_line.show()
        self._drop_line.raise_()
        self._scroll.ensureVisible(point.x(), point.y(), 0, 20)

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
        look_action = menu.addAction("外观设置…")
        hide_action = menu.addAction("收起成拉绳")
        trash_action = menu.addAction(f"回收站（{len(self._trash)}）")
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
        elif selected == look_action:
            self.open_appearance()
        elif selected == hide_action:
            self.collapse()
        elif selected == trash_action:
            self.open_trash()
        elif selected == remove_action:
            self.delete_requested.emit()

    def contextMenuEvent(self, event) -> None:
        self.open_menu(event.globalPos())

    def open_appearance(self) -> None:
        """Choose text colour, background colour, opacity and size, previewed live."""
        original = self._settings
        dialog = TodoAppearanceDialog(original, self)
        dialog.preview_changed.connect(self._preview_look)
        if dialog.exec() == TodoAppearanceDialog.DialogCode.Accepted:
            self.appearance_changed.emit(*dialog.choice())
        else:
            self.set_settings(original)

    def _preview_look(
        self, text: str, background: str, opacity: int, size: int, columns_after: int, cord: str
    ) -> None:
        self.set_settings(
            replace(
                self._settings,
                text_color=text,
                todo_background=background,
                todo_opacity=opacity,
                font_size=size,
                todo_columns_after=columns_after,
                todo_cord_style=cord,
            )
        )

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



class TodoAppearanceDialog(QDialog):
    """Pick a list's text colour, background colour, opacity and text size."""

    preview_changed = Signal(str, str, int, int, int, str)

    def __init__(self, settings: ReminderSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("待办清单外观")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(360)
        self.setStyleSheet(_DIALOG_STYLE)
        self._text = QColor(settings.text_color).name()
        self._background = QColor(settings.todo_background).name()
        self.text_button = QPushButton()
        self.background_button = QPushButton()
        self.text_button.clicked.connect(lambda: self._pick("text"))
        self.background_button.clicked.connect(lambda: self._pick("background"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(max(5, min(100, settings.todo_opacity)))
        self.opacity_label = QLabel()
        self.opacity.valueChanged.connect(self._changed)
        self.size_choice = QComboBox()
        for label, value in FONT_SIZES:
            self.size_choice.addItem(label, value)
        index = self.size_choice.findData(settings.font_size)
        self.size_choice.setCurrentIndex(index if index >= 0 else 1)
        self.size_choice.currentIndexChanged.connect(self._changed)
        self.columns_choice = QComboBox()
        for after in TODO_COLUMN_CHOICES:
            self.columns_choice.addItem("不双列" if after == 0 else f"超过 {after} 条时双列", after)
        index = self.columns_choice.findData(settings.todo_columns_after)
        self.columns_choice.setCurrentIndex(index if index >= 0 else self.columns_choice.findData(TODO_COLUMNS_AFTER))
        self.columns_choice.currentIndexChanged.connect(self._changed)
        self.cord_choice = QComboBox()
        for key in TODO_CORD_STYLES:
            self.cord_choice.addItem(pull_cord_art.style(key).label, key)
        index = self.cord_choice.findData(settings.todo_cord_style)
        self.cord_choice.setCurrentIndex(index if index >= 0 else 0)
        self.cord_choice.currentIndexChanged.connect(self._changed)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._reset)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        accept = QPushButton("确定")
        accept.setObjectName("primaryButton")
        accept.clicked.connect(self.accept)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("文字颜色", self.text_button)
        form.addRow("背景颜色", self.background_button)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_label)
        form.addRow("背景不透明度", opacity_row)
        form.addRow("字号", self.size_choice)
        form.addRow("条目多时", self.columns_choice)
        form.addRow("拉绳样式", self.cord_choice)
        buttons = QHBoxLayout()
        buttons.addWidget(reset)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(14)
        layout.addLayout(form)
        hint = QLabel("调整时清单会实时预览；不透明度越低，背景越透明。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(buttons)
        self._refresh()

    def choice(self) -> tuple[str, str, int, int, int, str]:
        return (
            self._text,
            self._background,
            self.opacity.value(),
            int(self.size_choice.currentData()),
            int(self.columns_choice.currentData()),
            str(self.cord_choice.currentData()),
        )

    def _pick(self, which: str) -> None:
        current = QColor(self._text if which == "text" else self._background)
        title = "选择待办文字颜色" if which == "text" else "选择待办背景颜色"
        color = pick_color(current, self, title)
        if not color.isValid():
            return
        if which == "text":
            self._text = color.name()
        else:
            self._background = color.name()
        self._changed()

    def _reset(self) -> None:
        self._text = TODO_TEXT
        self._background = TODO_BACK
        self.opacity.setValue(TODO_ALPHA)
        self.size_choice.setCurrentIndex(self.size_choice.findData(15))
        self.columns_choice.setCurrentIndex(self.columns_choice.findData(TODO_COLUMNS_AFTER))
        self.cord_choice.setCurrentIndex(self.cord_choice.findData(TODO_CORD))
        self._changed()

    def _changed(self, *_args) -> None:
        self._refresh()
        self.preview_changed.emit(*self.choice())

    def _refresh(self) -> None:
        for button, color in ((self.text_button, self._text), (self.background_button, self._background)):
            ink = "#000000" if QColor(color).lightnessF() > 0.55 else "#ffffff"
            button.setText(color.upper())
            button.setStyleSheet(
                f"background: {color}; color: {ink}; border: 1px solid {theme.LINE};"
                "border-radius: 7px; min-height: 30px;"
            )
        self.opacity_label.setText(f"{self.opacity.value()}%")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        theme.dark_title_bar(self)


_DIALOG_STYLE = f"""
QDialog {{ background: {theme.BACKGROUND}; }}
QLabel {{ color: {theme.TEXT}; font-family: {theme.FONT}; font-size: 13px; }}
QLabel#muted {{ color: {theme.MUTED}; font-size: 12px; }}
QPushButton {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    border-radius: 8px;
    padding: 0 14px;
    min-height: 30px;
    font-family: {theme.FONT};
    font-size: 13px;
}}
QPushButton:hover {{ background: {theme.HOVER}; border-color: {theme.MUTED}; }}
QPushButton#primaryButton {{ color: {theme.ACCENT_INK}; background: {theme.ACCENT}; border-color: {theme.ACCENT}; font-weight: 600; }}
QComboBox {{
    color: {theme.TEXT};
    background: {theme.RAISED};
    border: 1px solid {theme.LINE};
    border-radius: 7px;
    padding: 0 10px;
    min-height: 30px;
    font-family: {theme.FONT};
}}
QComboBox QAbstractItemView {{ color: {theme.TEXT}; background: {theme.RAISED}; selection-background-color: {theme.ACCENT}; selection-color: {theme.ACCENT_INK}; }}
QSlider::groove:horizontal {{ height: 4px; background: {theme.LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {theme.ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {theme.TEXT}; width: 14px; margin: -6px 0; border-radius: 7px; }}
"""


class TodoTrashDialog(QDialog):
    """Recently deleted items: restore them, or delete them for good."""

    restore_requested = Signal(object)
    purge_requested = Signal(object)

    def __init__(self, trash: tuple[TrashedItem, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("待办回收站")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.resize(440, 460)
        self.setStyleSheet(_DIALOG_STYLE + _TRASH_STYLE)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._update_buttons)
        self.empty = QLabel("回收站是空的。")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note = QLabel(
            f"删除的待办在这里保留 {todo_model.TRASH_DAYS} 天、最多 {todo_model.TRASH_LIMIT} 条，"
            "超出的会自动彻底删除。"
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.select_all = QPushButton("全选")
        self.restore_button = QPushButton("还原")
        self.restore_button.setObjectName("primaryButton")
        self.purge_button = QPushButton("彻底删除")
        self.empty_button = QPushButton("清空回收站")
        close = QPushButton("关闭")
        self.select_all.clicked.connect(self._toggle_all)
        self.restore_button.clicked.connect(self._restore)
        self.purge_button.clicked.connect(self._purge)
        self.empty_button.clicked.connect(self._empty)
        close.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addWidget(self.select_all)
        actions.addStretch()
        actions.addWidget(self.purge_button)
        actions.addWidget(self.restore_button)
        bottom = QHBoxLayout()
        bottom.addWidget(self.empty_button)
        bottom.addStretch()
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty, 1)
        layout.addLayout(actions)
        layout.addWidget(note)
        layout.addLayout(bottom)
        self.set_trash(trash)

    def set_trash(self, trash: tuple[TrashedItem, ...]) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for entry in trash:
            mark = "✓ " if entry.item.done else ""
            when = entry.deleted_at.replace("T", " ")[5:16]
            row = QListWidgetItem(f"{mark}{entry.item.text}\n删除于 {when}")
            row.setData(Qt.ItemDataRole.UserRole, entry.item.item_id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(row)
        self.list.blockSignals(False)
        self.list.setVisible(bool(trash))
        self.empty.setVisible(not trash)
        self.empty_button.setEnabled(bool(trash))
        self.select_all.setEnabled(bool(trash))
        self._update_buttons()

    def checked_ids(self) -> set[str]:
        return {
            self.list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.list.count())
            if self.list.item(index).checkState() == Qt.CheckState.Checked
        }

    def _update_buttons(self, *_args) -> None:
        chosen = bool(self.checked_ids())
        self.restore_button.setEnabled(chosen)
        self.purge_button.setEnabled(chosen)

    def _toggle_all(self) -> None:
        state = Qt.CheckState.Unchecked if len(self.checked_ids()) == self.list.count() else Qt.CheckState.Checked
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(state)

    def _restore(self) -> None:
        ids = self.checked_ids()
        if ids:
            self.restore_requested.emit(ids)

    def _purge(self) -> None:
        ids = self.checked_ids()
        if ids and self._confirm(f"彻底删除选中的 {len(ids)} 条待办吗？删除后无法恢复。"):
            self.purge_requested.emit(ids)

    def _empty(self) -> None:
        ids = {self.list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.list.count())}
        if ids and self._confirm(f"清空回收站里的 {len(ids)} 条待办吗？清空后无法恢复。"):
            self.purge_requested.emit(ids)

    def _confirm(self, question: str) -> bool:
        answer = QMessageBox.question(
            self, "待办回收站", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def showEvent(self, event) -> None:
        super().showEvent(event)
        theme.dark_title_bar(self)


_TRASH_STYLE = f"""
QListWidget {{
    color: {theme.TEXT};
    background: {theme.PANEL};
    border: 1px solid {theme.LINE};
    border-radius: 10px;
    padding: 4px;
    font-family: {theme.FONT};
    font-size: 13px;
    outline: none;
}}
QListWidget::item {{ padding: 6px 4px; border-bottom: 1px solid {theme.LINE}; }}
QListWidget::item:selected {{ background: {theme.HOVER}; color: {theme.TEXT}; }}
QPushButton:disabled {{ color: {theme.DISABLED}; }}
"""
