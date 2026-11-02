"""Pure rules of the desktop to-do list, kept apart from the window.

Items are stored in one ordered tuple. The list shows unfinished items first,
then finished ones; each group keeps the stored order and is numbered from 1.
Finishing an item moves it to the end of the finished group, and un-finishing
moves it to the end of the unfinished group.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

DEFAULT_TITLE = "待办清单"
MAX_TEXT_LENGTH = 500


@dataclass(frozen=True, slots=True)
class TodoItem:
    """One line of the list."""

    item_id: str
    text: str
    done: bool = False


def new_item(text: str) -> TodoItem:
    return TodoItem(uuid.uuid4().hex, clean_text(text))


def clean_text(text: str) -> str:
    """One line, no surrounding spaces, at most :data:`MAX_TEXT_LENGTH` characters."""
    return " ".join(text.split())[:MAX_TEXT_LENGTH]


def unfinished(items: tuple[TodoItem, ...]) -> tuple[TodoItem, ...]:
    return tuple(item for item in items if not item.done)


def finished(items: tuple[TodoItem, ...]) -> tuple[TodoItem, ...]:
    return tuple(item for item in items if item.done)


def display_order(items: tuple[TodoItem, ...]) -> tuple[TodoItem, ...]:
    """Unfinished items first, then finished ones."""
    return unfinished(items) + finished(items)


def add(items: tuple[TodoItem, ...], text: str) -> tuple[TodoItem, ...]:
    """Append a new unfinished item; empty text changes nothing."""
    cleaned = clean_text(text)
    if not cleaned:
        return items
    return display_order(items + (TodoItem(uuid.uuid4().hex, cleaned),))


def toggle(items: tuple[TodoItem, ...], item_id: str) -> tuple[TodoItem, ...]:
    """Finish or reopen one item and move it to the end of its new group."""
    target = _find(items, item_id)
    if target is None:
        return items
    others = tuple(item for item in items if item.item_id != item_id)
    changed = replace(target, done=not target.done)
    if changed.done:
        return unfinished(others) + finished(others) + (changed,)
    return unfinished(others) + (changed,) + finished(others)


def rename(items: tuple[TodoItem, ...], item_id: str, text: str) -> tuple[TodoItem, ...]:
    """Change one item's text; empty text keeps the old text."""
    cleaned = clean_text(text)
    if not cleaned:
        return items
    return tuple(replace(item, text=cleaned) if item.item_id == item_id else item for item in items)


def remove(items: tuple[TodoItem, ...], item_id: str) -> tuple[tuple[TodoItem, ...], TodoItem | None, int]:
    """Delete one item; also return it and its position so it can be restored."""
    ordered = display_order(items)
    for index, item in enumerate(ordered):
        if item.item_id == item_id:
            return ordered[:index] + ordered[index + 1:], item, index
    return ordered, None, -1


def restore(items: tuple[TodoItem, ...], item: TodoItem, index: int) -> tuple[TodoItem, ...]:
    """Put a deleted item back where it was."""
    ordered = display_order(items)
    position = max(0, min(index, len(ordered)))
    return display_order(ordered[:position] + (item,) + ordered[position:])


def move(items: tuple[TodoItem, ...], item_id: str, position: int) -> tuple[TodoItem, ...]:
    """Move one item to ``position`` within its own group (0 is the top)."""
    target = _find(items, item_id)
    if target is None:
        return items
    group = finished(items) if target.done else unfinished(items)
    rest = tuple(item for item in group if item.item_id != item_id)
    position = max(0, min(position, len(rest)))
    moved = rest[:position] + (target,) + rest[position:]
    if target.done:
        return unfinished(items) + moved
    return moved + finished(items)


def clear_finished(items: tuple[TodoItem, ...]) -> tuple[TodoItem, ...]:
    return unfinished(items)


def finish_all(items: tuple[TodoItem, ...]) -> tuple[TodoItem, ...]:
    return finished(items) + tuple(replace(item, done=True) for item in unfinished(items))


def counts(items: tuple[TodoItem, ...]) -> tuple[int, int]:
    """Return (unfinished, finished)."""
    open_count = len(unfinished(items))
    return open_count, len(items) - open_count


def to_values(items: tuple[TodoItem, ...]) -> list[dict]:
    """Plain values for the JSON settings file."""
    return [{"id": item.item_id, "text": item.text, "done": item.done} for item in items]


def from_values(values: object) -> tuple[TodoItem, ...]:
    """Read items from the settings file, skipping anything malformed."""
    if not isinstance(values, (list, tuple)):
        return ()
    items = []
    seen = set()
    for value in values:
        if isinstance(value, TodoItem):
            value = {"id": value.item_id, "text": value.text, "done": value.done}
        if not isinstance(value, dict):
            continue
        text = clean_text(str(value.get("text", "")))
        if not text:
            continue
        item_id = str(value.get("id") or value.get("item_id") or "") or uuid.uuid4().hex
        if item_id in seen:
            item_id = uuid.uuid4().hex
        seen.add(item_id)
        items.append(TodoItem(item_id, text, bool(value.get("done", False))))
    return display_order(tuple(items))


def _find(items: tuple[TodoItem, ...], item_id: str) -> TodoItem | None:
    return next((item for item in items if item.item_id == item_id), None)
