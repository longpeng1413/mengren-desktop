"""DPI-safe selection overlay composed from one native pane per monitor."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QCursor

from core.capture.desktop_capture import DesktopSnapshot
from core.capture.window_capture import WindowLocator
from ui.overlay import Overlay


class MultiScreenOverlay(QObject):
    """Coordinate independent monitor overlays in one global selection space."""

    selection_completed = Signal(QRect)
    cancelled = Signal()

    def __init__(
        self,
        snapshot: DesktopSnapshot,
        adjustable: bool = False,
        confirm_text: str = "开始",
        click_to_confirm: bool = False,
        show_confirmation_buttons: bool = True,
    ) -> None:
        super().__init__()
        self._virtual_geometry = QRect(snapshot.virtual_geometry)
        self._selected_window_handle = 0
        self._finished = False
        self._panes: list[Overlay] = []
        locator = WindowLocator(self._virtual_geometry)

        monitors = snapshot.monitors
        if monitors:
            pane_sources = tuple(
                (monitor.logical_geometry, monitor.image) for monitor in monitors
            )
        else:
            pane_sources = ((snapshot.virtual_geometry, snapshot.image),)

        for geometry, image in pane_sources:
            pane = Overlay(
                QRect(geometry),
                image,
                adjustable=adjustable,
                confirm_text=confirm_text,
                click_to_confirm=click_to_confirm,
                show_confirmation_buttons=show_confirmation_buttons,
                window_locator=locator,
            )
            pane.drag_selection_changed.connect(self._relay_drag_selection)
            pane.selection_completed.connect(
                lambda selection, source=pane: self._complete(source, selection)
            )
            pane.cancelled.connect(self._cancel)
            self._panes.append(pane)

    @property
    def selected_window_handle(self) -> int:
        """Return the HWND selected by clicking a detected window."""
        return self._selected_window_handle

    def geometry(self) -> QRect:
        """Return the complete logical virtual desktop geometry."""
        return QRect(self._virtual_geometry)

    def show(self) -> None:
        """Show all monitor panes without creating a cross-DPI giant window."""
        for pane in self._panes:
            pane.show()
            pane.raise_()

    def activateWindow(self) -> None:
        """Activate the pane currently under the pointer."""
        position = QCursor.pos()
        pane = next(
            (item for item in self._panes if item.geometry().contains(position)),
            self._panes[0] if self._panes else None,
        )
        if pane is not None:
            pane.activateWindow()
            pane.setFocus()

    def close(self) -> None:
        """Close every monitor pane."""
        for pane in self._panes:
            pane.close()

    def deleteLater(self) -> None:
        """Schedule all panes and the coordinator for deletion."""
        for pane in self._panes:
            pane.deleteLater()
        super().deleteLater()

    def _relay_drag_selection(self, selection: QRect) -> None:
        for pane in self._panes:
            pane.set_external_drag_selection(selection)

    def _complete(self, source: Overlay, selection: QRect) -> None:
        if self._finished:
            return
        self._finished = True
        self._selected_window_handle = source.selected_window_handle
        self.selection_completed.emit(selection)

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancelled.emit()
