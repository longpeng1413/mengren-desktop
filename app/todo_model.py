"""Pure rules of the desktop to-do list, kept apart from the window.

Items are stored in one ordered tuple. The list shows unfinished items first,
then finished ones; each group keeps the stored order and is numbered from 1.
Finishing an item moves it to the end of the finished group, and un-finishing
moves it to the end of the unfinished group.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

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


# ---------------------------------------------------------------- trash ----
# Deleted items wait in the list's own trash so they can be restored. To keep
# it from growing forever, items older than TRASH_DAYS and anything beyond
# TRASH_LIMIT (oldest first) are removed for good.

TRASH_DAYS = 30
TRASH_LIMIT = 200


@dataclass(frozen=True, slots=True)
class TrashedItem:
    """A deleted item and when it was deleted (ISO time, local)."""

    item: TodoItem
    deleted_at: str


def throw_away(
    trash: tuple[TrashedItem, ...],
    removed: tuple[TodoItem, ...],
    now: datetime | None = None,
) -> tuple[TrashedItem, ...]:
    """Put deleted items at the top of the trash (newest first)."""
    stamp = (now or datetime.now()).replace(microsecond=0).isoformat()
    fresh = tuple(TrashedItem(item, stamp) for item in removed)
    removed_ids = {item.item_id for item in removed}
    older = tuple(entry for entry in trash if entry.item.item_id not in removed_ids)
    return prune_trash(fresh + older, now)


def prune_trash(trash: tuple[TrashedItem, ...], now: datetime | None = None) -> tuple[TrashedItem, ...]:
    """Drop items older than :data:`TRASH_DAYS` and beyond :data:`TRASH_LIMIT`."""
    limit = (now or datetime.now()) - timedelta(days=TRASH_DAYS)
    kept = []
    for entry in trash:
        try:
            deleted = datetime.fromisoformat(entry.deleted_at)
        except ValueError:
            deleted = now or datetime.now()
        if deleted >= limit:
            kept.append(entry)
    return tuple(kept[:TRASH_LIMIT])


def restore_from_trash(
    items: tuple[TodoItem, ...],
    trash: tuple[TrashedItem, ...],
    item_ids: set[str],
) -> tuple[tuple[TodoItem, ...], tuple[TrashedItem, ...]]:
    """Move chosen items back to the end of their group in the list."""
    back = tuple(entry.item for entry in trash if entry.item.item_id in item_ids)
    present = {item.item_id for item in items}
    back = tuple(item for item in back if item.item_id not in present)
    remaining = tuple(entry for entry in trash if entry.item.item_id not in item_ids)
    return display_order(items + back), remaining


def purge(trash: tuple[TrashedItem, ...], item_ids: set[str]) -> tuple[TrashedItem, ...]:
    """Delete chosen items from the trash for good."""
    return tuple(entry for entry in trash if entry.item.item_id not in item_ids)


def forget(trash: tuple[TrashedItem, ...], item_id: str) -> tuple[TrashedItem, ...]:
    """Take one item back out of the trash (used by undo)."""
    return purge(trash, {item_id})


def trash_from_values(values: object, now: datetime | None = None) -> tuple[TrashedItem, ...]:
    """Read the trash from the settings file, pruning expired items."""
    if not isinstance(values, (list, tuple)):
        return ()
    entries = []
    for value in values:
        if isinstance(value, TrashedItem):
            entries.append(value)
            continue
        if not isinstance(value, dict):
            continue
        item_value = value.get("item", value)
        items = from_values([item_value])
        if not items:
            continue
        stamp = str(value.get("deleted_at") or (now or datetime.now()).replace(microsecond=0).isoformat())
        entries.append(TrashedItem(items[0], stamp))
    return prune_trash(tuple(entries), now)
