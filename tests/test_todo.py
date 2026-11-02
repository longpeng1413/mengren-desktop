"""Tests for the desktop to-do list: its rules, window and saving."""

import json
from dataclasses import asdict, replace

from PySide6.QtCore import QPoint, Qt
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
    widget.set_settings(replace(new_reminder("todo"), todo_items=_list(*texts)))
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
    widget.set_settings(replace(new_reminder("todo"), todo_items=_list(*long_texts)))

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

    widget.appearance_changed.emit("#112233", "#000000", 50, 17)

    look = saved[-1][0]
    assert (look.text_color, look.todo_background, look.todo_opacity, look.font_size) == ("#112233", "#000000", 50, 17)
    manager.shutdown()
