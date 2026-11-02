"""Tests for the desktop to-do list: its rules, window and saving."""

import json
from dataclasses import asdict, replace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import todo_model as todo
from app.reminder_preferences import _settings_from_values, new_reminder
from ui import reminder_widget
from ui.todo_widget import TodoListWidget


def _texts(items) -> list[tuple[str, bool]]:
    return [(item.text, item.done) for item in items]


def _list(*texts: str):
    items = ()
    for text in texts:
        items = todo.add(items, text)
    return items


# ---------------------------------------------------------------- rules ----


def test_finished_items_go_to_the_end_and_come_back_to_the_open_group() -> None:
    items = _list("a", "b", "c")

    items = todo.toggle(items, items[0].item_id)
    assert _texts(items) == [("b", False), ("c", False), ("a", True)]

    items = todo.toggle(items, items[1].item_id)
    assert _texts(items) == [("b", False), ("a", True), ("c", True)]

    items = todo.toggle(items, items[1].item_id)
    assert _texts(items) == [("b", False), ("a", False), ("c", True)]
    assert todo.counts(items) == (2, 1)


def test_new_items_join_the_open_group_above_finished_ones() -> None:
    items = _list("a", "b")
    items = todo.toggle(items, items[0].item_id)

    items = todo.add(items, "  新的\n 一条  ")

    assert _texts(items) == [("b", False), ("新的 一条", False), ("a", True)]
    assert todo.add(items, "   ") == items


def test_a_deleted_item_can_be_restored_in_place() -> None:
    items = _list("a", "b", "c")

    remaining, removed, index = todo.remove(items, items[1].item_id)
    assert _texts(remaining) == [("a", False), ("c", False)]

    assert _texts(todo.restore(remaining, removed, index)) == _texts(items)


def test_items_move_only_within_their_own_group() -> None:
    items = _list("a", "b", "c", "d")
    items = todo.toggle(items, items[3].item_id)

    moved = todo.move(items, items[2].item_id, 0)
    assert _texts(moved) == [("c", False), ("a", False), ("b", False), ("d", True)]

    moved = todo.move(items, items[0].item_id, 99)
    assert _texts(moved) == [("b", False), ("c", False), ("a", False), ("d", True)]


def test_rename_clear_and_finish_all() -> None:
    items = _list("a", "b")

    items = todo.rename(items, items[0].item_id, "甲")
    assert _texts(items)[0] == ("甲", False)
    assert todo.rename(items, items[0].item_id, "  ") == items

    items = todo.finish_all(items)
    assert todo.counts(items) == (0, 2)
    assert todo.clear_finished(items) == ()


def test_lists_are_saved_and_read_back() -> None:
    reminder = new_reminder("todo")
    items = _list("交易流程的制定", "复盘")
    reminder = replace(reminder, todo_title="本周", todo_items=todo.toggle(items, items[0].item_id))

    loaded = _settings_from_values(json.loads(json.dumps(asdict(reminder))))

    assert loaded.kind == "todo"
    assert loaded.todo_title == "本周"
    assert _texts(loaded.todo_items) == [("复盘", False), ("交易流程的制定", True)]
    assert todo.from_values([{"text": ""}, "x", {"text": "ok", "done": 1}])[0].done


# --------------------------------------------------------------- window ----


def _widget(*texts: str) -> TodoListWidget:
    _app = QApplication.instance() or QApplication([])
    widget = TodoListWidget()
    widget.set_settings(replace(new_reminder("todo"), todo_items=_list(*texts), todo_collapsed=False))
    widget.show()
    QApplication.processEvents()
    return widget


def _row(widget: TodoListWidget, text: str):
    return next(row for row in widget._rows if row.item.text == text)


def test_rows_are_numbered_per_group_with_counts() -> None:
    widget = _widget("a", "b", "c")
    saved = []
    widget.items_changed.connect(saved.append)

    _row(widget, "a").check.click()

    numbers = [(row.item.text, row.number.text()) for row in widget._rows]
    assert numbers == [("b", "1."), ("c", "2."), ("a", "1.")]
    assert widget.counts.text() == "未完成 2 · 已完成 1"
    assert _row(widget, "a").text.font().strikeOut()
    assert _texts(saved[-1]) == [("b", False), ("c", False), ("a", True)]
    widget.close()


def test_typing_adds_items_and_keeps_the_box_ready() -> None:
    widget = _widget()
    widget.input.setFocus()

    # QTest cannot type Chinese key by key (it crashes); real input goes
    # through the input method, which fills the box like setText does.
    for text in ("第一条", "第二条"):
        widget.input.setText(text)
        QTest.keyClick(widget.input, Qt.Key.Key_Return)

    assert _texts(widget.items) == [("第一条", False), ("第二条", False)]
    assert widget.input.text() == ""
    widget.close()


def test_delete_shows_undo_and_undo_restores() -> None:
    widget = _widget("a", "b")

    _row(widget, "a").delete.click()
    assert _texts(widget.items) == [("b", False)]
    assert not widget._undo_bar.isHidden()

    widget.undo_button.click()
    assert _texts(widget.items) == [("a", False), ("b", False)]
    assert widget._undo_bar.isHidden()
    widget.close()


def test_double_click_edits_a_row_in_place() -> None:
    widget = _widget("a")
    row = _row(widget, "a")

    QTest.mouseDClick(row, Qt.MouseButton.LeftButton, pos=QPoint(60, 8))
    row.editor.setText("改过的")
    QTest.keyClick(row.editor, Qt.Key.Key_Return)

    assert _texts(widget.items) == [("改过的", False)]
    widget.close()


def test_dragging_a_row_reorders_it() -> None:
    widget = _widget("a", "b", "c")
    first = _row(widget, "a")
    last = _row(widget, "c")
    below_last = last.mapToGlobal(QPoint(10, last.height() - 2))

    widget.begin_row_drag(first)
    widget.continue_row_drag(first, below_last)
    widget.finish_row_drag(first)

    assert [item.text for item in widget.items] == ["b", "c", "a"]
    widget.close()


def test_f3_todo_button_creates_a_saved_list(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    saved = []
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda items: saved.append(list(items)))
    manager = reminder_widget.DesktopReminderManager()

    manager.launcher.buttons["todo"].click()
    QApplication.processEvents()
    widget = next(iter(manager._widgets.values()))
    widget.add_item("续费")

    assert isinstance(widget, TodoListWidget)
    assert saved[-1][0].kind == "todo"
    assert _texts(saved[-1][0].todo_items) == [("续费", False)]
    manager.shutdown()


# ----------------------------------------------------------- appearance ----

from ui.todo_widget import TodoAppearanceDialog, palette_for  # noqa: E402


def test_helper_colours_follow_the_background() -> None:
    light = palette_for("#222222", "#ffffff", 78)
    dark = palette_for("#fff4d6", "#101820", 50)

    assert light.muted == "#6b6b6b"
    assert dark.muted != light.muted
    assert light.card == "rgba(255, 255, 255, 199)"
    assert dark.card == "rgba(16, 24, 32, 127)"


def test_every_line_shows_when_restored_before_being_shown() -> None:
    _app = QApplication.instance() or QApplication([])
    long_texts = [f"第{i}条：复盘守最大二反转或者主拉峰级离场和反手的合理性" for i in range(7)]
    widget = TodoListWidget()
    widget.set_settings(replace(new_reminder("todo"), todo_items=_list(*long_texts), todo_collapsed=False))

    widget.show()
    for _ in range(5):
        QApplication.processEvents()

    assert widget._scroll.verticalScrollBar().maximum() == 0
    assert widget._scroll.height() > 7 * 30
    widget.close()


def test_appearance_is_previewed_saved_or_restored() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = _widget("a")
    saved = []
    widget.appearance_changed.connect(lambda *values: saved.append(values))
    original = widget._settings

    dialog = TodoAppearanceDialog(original, widget)
    dialog.preview_changed.connect(widget._preview_look)
    dialog.opacity.setValue(40)
    assert widget._settings.todo_opacity == 40
    assert dialog.choice()[2] == 40

    widget.set_settings(original)
    assert widget._settings.todo_opacity == original.todo_opacity
    assert widget._rows[0].check.size().width() == 16
    widget.close()


def test_manager_saves_the_chosen_look(monkeypatch) -> None:
    _app = QApplication.instance() or QApplication([])
    saved = []
    monkeypatch.setattr(reminder_widget, "load_reminders", lambda: [])
    monkeypatch.setattr(reminder_widget, "save_reminders", lambda items: saved.append(list(items)))
    manager = reminder_widget.DesktopReminderManager()
    manager.launcher.buttons["todo"].click()
    QApplication.processEvents()
    widget = next(iter(manager._widgets.values()))

    widget.appearance_changed.emit("#112233", "#000000", 50, 17, 8)

    look = saved[-1][0]
    assert (look.text_color, look.todo_background, look.todo_opacity, look.font_size) == ("#112233", "#000000", 50, 17)
    assert look.todo_columns_after == 8
    manager.shutdown()



# ------------------------------------------------------------ pull cord ----

from ui.todo_widget import _PullCord  # noqa: E402


def _cord_widget(*texts: str, collapsed: bool = True) -> TodoListWidget:
    _app = QApplication.instance() or QApplication([])
    widget = TodoListWidget()
    widget.set_settings(replace(new_reminder("todo"), todo_items=_list(*texts), todo_collapsed=collapsed))
    widget.move(400, 200)
    widget.show()
    QApplication.processEvents()
    return widget


def _hook(widget: TodoListWidget) -> QPoint:
    return widget.cord.mapToGlobal(QPoint(widget.cord.width() // 2, 0))


def test_a_closed_list_is_only_its_cord_and_a_click_opens_it() -> None:
    widget = _cord_widget("a", "b")
    states = []
    widget.collapsed_changed.connect(states.append)
    hook = _hook(widget)

    assert widget.width() == _PullCord.WIDTH
    assert widget._card.isHidden()
    knob = QPoint(widget.cord.width() // 2, widget.cord.height() - 10)
    QTest.mouseClick(widget.cord, Qt.MouseButton.LeftButton, pos=knob)

    assert not widget._card.isHidden()
    assert states == [False]
    assert _hook(widget).x() == hook.x() and _hook(widget).y() == hook.y()
    widget.close()


def test_pulling_the_knob_far_enough_opens_and_a_short_pull_springs_back() -> None:
    widget = _cord_widget("a")
    knob = QPoint(widget.cord.width() // 2, widget.cord.height() - 10)

    QTest.mousePress(widget.cord, Qt.MouseButton.LeftButton, pos=knob)
    QTest.mouseMove(widget.cord, knob + QPoint(0, 12))
    QTest.mouseRelease(widget.cord, Qt.MouseButton.LeftButton, pos=knob + QPoint(0, 12))
    assert widget.collapsed

    knob = QPoint(widget.cord.width() // 2, widget.cord.height() - 10)
    QTest.mousePress(widget.cord, Qt.MouseButton.LeftButton, pos=knob)
    QTest.mouseMove(widget.cord, knob + QPoint(0, 60))
    assert widget.cord.pull == 60
    QTest.mouseRelease(widget.cord, Qt.MouseButton.LeftButton, pos=knob + QPoint(0, 60))
    assert not widget.collapsed
    assert widget.cord.pull == 0
    widget.close()


def test_clicking_the_hook_or_hide_closes_and_dragging_the_hook_moves() -> None:
    widget = _cord_widget("a", collapsed=False)
    moved = []
    widget.position_saved.connect(moved.append)

    widget.hide_button.click()
    assert widget.collapsed
    widget.toggle_collapsed()
    assert not widget.collapsed

    start = QPoint(widget.pos())
    QTest.mousePress(widget.cord, Qt.MouseButton.LeftButton, pos=QPoint(widget.cord.width() // 2, 4))
    QTest.mouseMove(widget.cord, QPoint(widget.cord.width() // 2 + 40, 24))
    QTest.mouseRelease(widget.cord, Qt.MouseButton.LeftButton, pos=QPoint(widget.cord.width() // 2 + 40, 24))
    assert widget.pos() == start + QPoint(40, 20)
    assert not widget.collapsed
    assert moved[-1] == widget.pos()
    widget.close()


# ---------------------------------------------------------- two columns ----


def test_a_long_group_switches_to_two_columns_and_widens() -> None:
    widget = _widget(*[f"第{i}条" for i in range(12)])
    open_group = widget._list_layout.itemAt(0).widget()

    assert len(open_group.columns) == 2
    assert [len(column) for column in open_group.columns] == [6, 6]
    assert [row.number.text() for row in open_group.columns[1]][:2] == ["7.", "8."]
    assert widget.width() > widget.base_width * 2
    widget.close()


def test_two_columns_can_be_switched_off() -> None:
    _app = QApplication.instance() or QApplication([])
    widget = TodoListWidget()
    widget.set_settings(replace(
        new_reminder("todo"), todo_items=_list(*[str(i) for i in range(12)]), todo_collapsed=False, todo_columns_after=0
    ))
    widget.show()
    QApplication.processEvents()

    assert len(widget._list_layout.itemAt(0).widget().columns) == 1
    assert widget.width() == widget.base_width
    widget.close()


def test_dragging_into_the_second_column_reorders() -> None:
    widget = _widget(*[f"项{i}" for i in range(12)])
    for _ in range(3):
        QApplication.processEvents()
    first = _row(widget, "项0")
    target = _row(widget, "项8")
    below_target = target.mapToGlobal(QPoint(10, target.height() - 2))

    widget.begin_row_drag(first)
    widget.continue_row_drag(first, below_target)
    widget.finish_row_drag(first)

    texts = [item.text for item in widget.items]
    assert texts.index("项0") == texts.index("项8") + 1
    widget.close()


def test_choosing_a_text_colour_really_changes_it(monkeypatch) -> None:
    # The size box was once named "size", hiding QWidget.size(): the colour
    # window then failed to open and colours could not be changed.
    _app = QApplication.instance() or QApplication([])
    seen = []

    def fake_pick(initial, anchor, title):
        seen.append(anchor.size())
        return QColor("#ff0000")

    monkeypatch.setattr("ui.todo_widget.pick_color", fake_pick)
    dialog = TodoAppearanceDialog(new_reminder("todo"))

    dialog.text_button.click()
    dialog.background_button.click()

    assert dialog.choice()[:2] == ("#ff0000", "#ff0000")
    assert len(seen) == 2
    dialog.deleteLater()
