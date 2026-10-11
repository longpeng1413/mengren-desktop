"""Coordinates desktop capture, selection, long capture, and the editor."""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QImage

from core.capture.desktop_capture import DesktopCaptureEngine, DesktopSnapshot
from core.capture.monitor_manager import MonitorManager
from app.preferences import PresentationShortcutSettings
from core.long_capture.scroll_capture import ScrollCaptureSession
from ui.editor import Editor
from ui.long_capture_controls import LongCaptureControls
from ui.long_capture_frame import LongCaptureFrame
from ui.multi_screen_overlay import MultiScreenOverlay
from ui.overlay_editor import OverlayEditor
from ui.pinned_image import PinnedImageWindow
from ui.presentation_overlay import PresentationOverlay


class CaptureService(QObject):
    """Application service for ordinary and scrolling screenshots."""

    capture_failed = Signal(str)
    presentation_active_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._monitor_manager = MonitorManager()
        self._engine = DesktopCaptureEngine()
        self._overlay: MultiScreenOverlay | None = None
        self._editor: Editor | OverlayEditor | None = None
        self._snapshot: DesktopSnapshot | None = None
        self._long_session: ScrollCaptureSession | None = None
        self._long_frame: LongCaptureFrame | None = None
        self._long_controls: LongCaptureControls | None = None
        self._capture_mode = "normal"
        self._target_window = 0
        self._pinned_images: list[PinnedImageWindow] = []
        self._presentation_overlay: PresentationOverlay | None = None
        self._presentation_shortcuts = PresentationShortcutSettings()
        self._presentation_suspended_for_capture = False

    def start_capture(self) -> None:
        """Start a normal F1 area screenshot."""
        self._start_selection("normal")

    def start_long_capture(self) -> None:
        """Start user-scrolled F2 capture, or finish one already in progress."""
        if self._long_session is not None:
            self._long_session.finish()
            return
        self._start_selection("long")

    def configure_presentation_shortcuts(
        self,
        shortcuts: PresentationShortcutSettings,
    ) -> None:
        """Use updated tool shortcuts for the next F5 presentation session."""
        self._presentation_shortcuts = shortcuts

    def toggle_presentation(self) -> None:
        """Start or stop the transparent F5 desktop presentation layer."""
        if self._presentation_overlay is not None:
            self._presentation_overlay.close()
            return
        if (
            self._overlay is not None
            or self._editor is not None
            or self._long_session is not None
        ):
            return
        self._monitor_manager.refresh()
        geometry = self._monitor_manager.virtual_geometry
        if geometry.isEmpty():
            return
        overlay = PresentationOverlay(geometry, self._presentation_shortcuts)
        overlay.closed.connect(self._presentation_closed)
        self._presentation_overlay = overlay
        overlay.show()
        overlay.raise_()
        overlay.activateWindow()
        self.presentation_active_changed.emit(True)

    def execute_presentation_shortcut(self, action: str) -> None:
        """Dispatch one configured temporary shortcut to the active F5 overlay."""
        if self._presentation_overlay is not None:
            self._presentation_overlay.execute_shortcut(action)

    def restore_presentation_toolbar(self) -> None:
        """Restore the F5 toolbar after another top-level UI briefly takes focus."""
        if self._presentation_overlay is not None:
            self._presentation_overlay.restore_toolbar()

    def _start_selection(self, mode: str) -> None:
        if self._overlay is not None or self._long_session is not None:
            return
        if self._presentation_overlay is not None and mode != "normal":
            return

        self._monitor_manager.refresh()
        geometry = self._monitor_manager.virtual_geometry
        if geometry.isEmpty():
            return

        try:
            self._snapshot = self._engine.capture(geometry)
        except Exception as error:
            self.capture_failed.emit(f"无法读取桌面画面：{error}")
            return

        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            self._snapshot = None
            return
        if self._snapshot.image.isNull():
            self._snapshot = None
            self.capture_failed.emit("无法读取鼠标所在屏幕的画面。")
            return

        if self._presentation_overlay is not None:
            self._presentation_overlay.suspend()
            self._presentation_suspended_for_capture = True

        self._capture_mode = mode
        self._target_window = self._foreground_window()
        self._overlay = MultiScreenOverlay(
            self._snapshot,
            adjustable=mode == "long",
            click_to_confirm=mode == "long",
            show_confirmation_buttons=False,
        )
        self._overlay.selection_completed.connect(self._complete_selection)
        self._overlay.cancelled.connect(self._cancel_capture)
        self._overlay.show()
        self._overlay.activateWindow()

    def _complete_selection(self, selection: QRect) -> None:
        if self._snapshot is None:
            self._cancel_capture()
            return

        snapshot = self._snapshot
        first_frame = snapshot.crop(selection)
        mode = self._capture_mode
        geometry = self._monitor_manager.virtual_geometry
        target_window = self._target_window
        self._dispose_overlay()

        if first_frame.isNull():
            self._resume_presentation()
            return
        if mode == "long":
            self._start_scroll_session(
                geometry,
                selection,
                first_frame,
                target_window,
            )
            return
        self._show_editor(first_frame, selection, snapshot)

    def _start_scroll_session(
        self,
        geometry: QRect,
        selection: QRect,
        first_frame: QImage,
        target_window: int,
    ) -> None:
        self._long_frame = LongCaptureFrame(selection)
        self._long_frame.show()
        self._long_frame.raise_()
        self._long_frame.exclude_from_capture()
        session = ScrollCaptureSession(
            self._engine,
            geometry,
            selection,
            first_frame,
            target_window,
        )
        session.completed.connect(self._complete_long_capture)
        session.failed.connect(self._fail_long_capture)
        session.cancelled.connect(self._cancel_long_capture)
        controls = LongCaptureControls(selection)
        controls.automatic_mode_requested.connect(session.set_automatic_mode)
        controls.pause_requested.connect(session.pause)
        controls.resume_requested.connect(session.resume)
        controls.finish_requested.connect(session.finish)
        controls.cancel_requested.connect(session.cancel)
        session.status_changed.connect(controls.set_status)
        session.attention_required.connect(controls.show_attention)
        session.automatic_mode_changed.connect(controls.set_automatic_mode)
        session.paused_changed.connect(controls.set_paused)
        controls.show()
        controls.raise_()
        controls.exclude_from_capture()
        self._long_controls = controls
        self._long_session = session
        session.start()

    def _complete_long_capture(self, image: QImage) -> None:
        self._dispose_long_session()
        self._show_editor(image)

    def _fail_long_capture(self, message: str) -> None:
        self._dispose_long_session()
        self.capture_failed.emit(message)

    def _cancel_long_capture(self) -> None:
        self._dispose_long_session()

    def _show_editor(
        self,
        image: QImage,
        placement: QRect | None = None,
        snapshot: DesktopSnapshot | None = None,
    ) -> None:
        if placement is not None and snapshot is not None:
            self._editor = OverlayEditor(snapshot, placement)
        else:
            self._editor = Editor(image)
        self._editor.finished.connect(self._clear_editor)
        self._editor.pin_requested.connect(self._show_pinned_image)
        self._editor.show()
        self._editor.raise_()
        self._editor.activateWindow()

    def _cancel_capture(self) -> None:
        self._dispose_overlay()
        self._resume_presentation()

    def _dispose_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay.deleteLater()
        self._overlay = None
        self._snapshot = None

    def _dispose_long_session(self) -> None:
        if self._long_session is not None:
            self._long_session.deleteLater()
        self._long_session = None
        if self._long_frame is not None:
            self._long_frame.close()
            self._long_frame.deleteLater()
        self._long_frame = None
        if self._long_controls is not None:
            self._long_controls.close()
            self._long_controls.deleteLater()
        self._long_controls = None

    def _hide_long_frame_for_capture(self) -> None:
        """Avoid recording the visible selection border into the final image."""
        if self._long_frame is not None:
            self._long_frame.hide()

    def _show_long_frame_after_capture(self) -> None:
        """Restore the visible selection boundary immediately after one sample."""
        if self._long_frame is not None:
            self._long_frame.show()
            self._long_frame.raise_()

    def _clear_editor(self) -> None:
        self._editor = None
        self._resume_presentation()

    def _presentation_closed(self) -> None:
        """Release the F5 overlay and temporary presentation shortcuts."""
        self._presentation_overlay = None
        self._presentation_suspended_for_capture = False
        self.presentation_active_changed.emit(False)

    def _resume_presentation(self) -> None:
        """Restore F5 annotations after an F1 capture flow has finished."""
        if not self._presentation_suspended_for_capture:
            return
        self._presentation_suspended_for_capture = False
        if self._presentation_overlay is not None:
            self._presentation_overlay.resume()

    def _show_pinned_image(self, image: QImage, position, display_size) -> None:
        """Show one detached, movable screenshot while retaining its Python reference."""
        pinned = PinnedImageWindow(image, position, display_size)
        pinned.edit_requested.connect(lambda window=pinned: self._edit_pinned_image(window))
        pinned.destroyed.connect(lambda _object, window=pinned: self._forget_pinned_image(window))
        self._pinned_images.append(pinned)
        pinned.show()
        pinned.raise_()
        pinned.activateWindow()

    def _edit_pinned_image(self, window: PinnedImageWindow) -> None:
        """Open one pinned image in the full editor and apply changes back to it."""
        if self._editor is not None:
            return
        window.hide()
        editor = Editor(window.image(), apply_mode=True)
        editor.image_applied.connect(window.set_image)
        editor.finished.connect(
            lambda _result, target=window, active_editor=editor: self._finish_pinned_edit(
                target,
                active_editor,
            )
        )
        self._editor = editor
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _finish_pinned_edit(
        self,
        window: PinnedImageWindow,
        editor: Editor,
    ) -> None:
        """Return the existing sticker after its editor closes."""
        if self._editor is editor:
            self._editor = None
        window.show()
        window.raise_()
        window.activateWindow()

    def _forget_pinned_image(self, window: PinnedImageWindow) -> None:
        """Release references to stickers that the user has closed."""
        if window in self._pinned_images:
            self._pinned_images.remove(window)

    @staticmethod
    def _foreground_window() -> int:
        return int(ctypes.windll.user32.GetForegroundWindow())
