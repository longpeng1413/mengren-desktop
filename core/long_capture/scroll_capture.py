"""Stable automatic/manual Windows scroll capture session."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QImage

from core.capture.desktop_capture import DesktopCaptureEngine
from core.long_capture.scroll_input import send_vertical_wheel
from core.long_capture.stitch import VerticalStitcher


class ScrollCaptureSession(QObject):
    """Capture settled scroll steps and never silently skip a broken seam."""

    completed = Signal(QImage)
    failed = Signal(str)
    cancelled = Signal()
    status_changed = Signal(str)
    attention_required = Signal(str)
    automatic_mode_changed = Signal(bool)
    paused_changed = Signal(bool)

    _START_DELAY_MS = 140
    _AUTO_FIRST_SAMPLE_MS = 60
    _SETTLE_SAMPLE_MS = 75
    _SETTLE_REQUIRED_SAMPLES = 2
    _SETTLE_MAX_SAMPLES = 16
    _MAX_TRANSITION_FRAMES = 12
    _NEXT_STEP_DELAY_MS = 80
    _MANUAL_POLL_INTERVAL_MS = 100
    _BOTTOM_CONFIRMATIONS = 5
    _BOTTOM_PROBE_DELAY_MS = 180
    _BOTTOM_PROBE_NOTCHES = 1
    _INITIAL_WHEEL_NOTCHES = 4
    _MIN_WHEEL_NOTCHES = 2
    _MAX_WHEEL_NOTCHES = 5

    def __init__(
        self,
        engine: DesktopCaptureEngine,
        virtual_geometry: QRect,
        selection: QRect,
        first_frame: QImage,
        target_window: int,
        before_capture: Callable[[], None] | None = None,
        after_capture: Callable[[], None] | None = None,
        scroll_handler: Callable[[int, int, int], bool] | None = None,
    ) -> None:
        super().__init__()
        self._engine = engine
        self._virtual_geometry = QRect(virtual_geometry)
        self._selection = QRect(selection)
        self._target_window = target_window
        self._before_capture = before_capture
        self._after_capture = after_capture
        self._stitcher = VerticalStitcher(first_frame)
        self._scroll_handler = scroll_handler or send_vertical_wheel
        self._has_new_content = False
        self._finished = False
        self._escape_was_down = False
        self._automatic = True
        self._paused = False
        self._schedule_generation = 0
        self._wheel_notches = self._INITIAL_WHEEL_NOTCHES
        self._step_count = 0
        self._bottom_confirmations = 0
        self._settle_frames: list[QImage] = []
        self._settle_stable_samples = 0
        self._manual_previous: QImage | None = None
        self._manual_stable_samples = 0
        self._manual_frames: list[QImage] = []
        self._recovering_overlap = False

    @property
    def automatic(self) -> bool:
        return self._automatic

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        """Return to the selected window and start the chosen capture mode."""
        self._restore_target_window()
        self.automatic_mode_changed.emit(True)
        self.status_changed.emit("自动长截图：准备分段滚动")
        self._schedule(self._START_DELAY_MS, self._begin_auto_step)

    def finish(self) -> None:
        """Stop capture and open only the verified image accumulated so far."""
        if self._finished:
            return
        self._finished = True
        self._schedule_generation += 1
        self.completed.emit(self._stitcher.image)

    def cancel(self) -> None:
        """Discard the current long capture and close its visible helpers."""
        if self._finished:
            return
        self._finished = True
        self._schedule_generation += 1
        self.cancelled.emit()

    def pause(self) -> None:
        if self._finished or self._paused:
            return
        self._paused = True
        self._schedule_generation += 1
        self.paused_changed.emit(True)
        self.status_changed.emit("长截图已暂停，可在目标窗口调整位置")

    def resume(self) -> None:
        if self._finished or not self._paused:
            return
        self._paused = False
        self._schedule_generation += 1
        self.paused_changed.emit(False)
        self._restore_target_window()
        if self._automatic:
            self.status_changed.emit("自动长截图：继续")
            self._schedule(self._START_DELAY_MS, self._begin_auto_step)
        else:
            self.status_changed.emit("手动模式：滚动后停稳，按 F2 完成")
            self._reset_manual_observation()
            self._schedule(self._MANUAL_POLL_INTERVAL_MS, self._poll_manual_frame)

    def set_automatic_mode(self, enabled: bool) -> None:
        """Switch between controlled automatic steps and compatible manual wheel mode."""
        if self._finished:
            return
        enabled = bool(enabled)
        self._automatic = enabled
        self._paused = False
        self._schedule_generation += 1
        self._bottom_confirmations = 0
        self._settle_frames.clear()
        self._recovering_overlap = False
        self._reset_manual_observation()
        self.automatic_mode_changed.emit(enabled)
        self.paused_changed.emit(False)
        self._restore_target_window()
        if enabled:
            self.status_changed.emit("自动模式：分段滚动并等待画面稳定")
            self._schedule(self._START_DELAY_MS, self._begin_auto_step)
        else:
            self.status_changed.emit("手动模式：滚动后停稳，按 F2 完成")
            self._schedule(self._MANUAL_POLL_INTERVAL_MS, self._poll_manual_frame)

    def _begin_auto_step(self) -> None:
        if not self._vertical_ready(automatic=True):
            return
        if self._escape_pressed():
            self.cancel()
            return
        self._restore_target_window()
        scroll_x, scroll_y, wheel_notches = self._automatic_scroll_target()
        self._step_count += 1
        self.status_changed.emit(f"自动滚动第 {self._step_count} 段，正在等待画面稳定")
        if not self._scroll_handler(scroll_x, scroll_y, -wheel_notches):
            self._switch_to_manual(
                "目标窗口不接受自动滚轮，已切换手动模式"
            )
            return
        self._settle_frames.clear()
        self._settle_stable_samples = 0
        self._schedule(self._AUTO_FIRST_SAMPLE_MS, self._collect_auto_sample)

    def _collect_auto_sample(self) -> None:
        if not self._vertical_ready(automatic=True):
            return
        if self._escape_pressed():
            self.cancel()
            return
        frame = self._capture_current_frame()
        if frame is None:
            return
        if self._settle_frames and VerticalStitcher.frames_share_position(
            self._settle_frames[-1], frame
        ):
            self._settle_stable_samples += 1
        else:
            self._settle_stable_samples = 0
        self._settle_frames.append(frame)
        settled = self._settle_stable_samples >= self._SETTLE_REQUIRED_SAMPLES
        timed_out = len(self._settle_frames) >= self._SETTLE_MAX_SAMPLES
        if settled:
            self._commit_auto_frames()
            return
        if timed_out:
            self._pause_with_attention(
                "页面持续变化，未在稳定状态下拼接；请暂停动画后点击继续"
            )
            return
        self._schedule(self._SETTLE_SAMPLE_MS, self._collect_auto_sample)

    def _commit_auto_frames(self) -> None:
        if not self._vertical_ready(automatic=True) or not self._settle_frames:
            return
        result = self._accept_stable_batch(self._settle_frames)
        self._settle_frames = []
        if self._finished:
            return
        if result == "stationary":
            self.status_changed.emit(
                f"正在确认页面底部 {self._bottom_confirmations}/{self._BOTTOM_CONFIRMATIONS}"
            )
            if self._bottom_confirmations >= self._BOTTOM_CONFIRMATIONS:
                if self._has_new_content:
                    self.finish()
                else:
                    self._switch_to_manual(
                        "未检测到自动滚动；请使用手动滚轮，按 F2 完成"
                    )
            else:
                self._schedule(self._BOTTOM_PROBE_DELAY_MS, self._begin_auto_step)
            return
        if result == "appended":
            self._adapt_scroll_step()
            self.status_changed.emit(
                f"已完成 {self._step_count} 段，当前长图 {self._stitcher.total_height} 像素"
            )
            self._schedule(self._NEXT_STEP_DELAY_MS, self._begin_auto_step)
            return
        self._pause_for_mismatch()

    def _automatic_scroll_target(self) -> tuple[int, int, int]:
        """Move bottom probes away from nested content that may swallow the wheel."""
        center = self._selection.center()
        if self._bottom_confirmations <= 0:
            return center.x(), center.y(), self._wheel_notches

        width = max(1, self._selection.width())
        height = max(1, self._selection.height())
        inset = max(8, min(48, width // 8))
        left = min(self._selection.right(), self._selection.left() + inset)
        right = max(self._selection.left(), self._selection.right() - inset)
        upper = min(self._selection.bottom(), self._selection.top() + height // 3)
        lower = max(self._selection.top(), self._selection.top() + (height * 2) // 3)
        probe_points = (
            (left, center.y()),
            (right, center.y()),
            (left, upper),
            (right, lower),
        )
        point = probe_points[(self._bottom_confirmations - 1) % len(probe_points)]
        return point[0], point[1], self._BOTTOM_PROBE_NOTCHES

    def _accept_stable_batch(self, frames: list[QImage]) -> str:
        """Append a stable frame, using transition frames to recover overlap."""
        if not frames:
            return "failed"
        final = frames[-1]
        if self._stitcher.is_same_position(final):
            self._bottom_confirmations += 1
            return "stationary"

        if self._stitcher.append(final):
            self._mark_append()
            return "appended"

        appended = False
        for candidate in frames:
            if self._stitcher.is_same_position(candidate):
                continue
            if self._stitcher.append(candidate):
                appended = True
                self._mark_append()
        if appended:
            self._bottom_confirmations = 0
            return "appended"
        self._bottom_confirmations = 0
        return "failed"

    def _adapt_scroll_step(self) -> None:
        match = self._stitcher.last_match
        if match is None:
            return
        height = self._selection.height()
        if height <= 0:
            return
        fresh_ratio = (height - match.overlap) / height
        if fresh_ratio > 0.62:
            self._wheel_notches = max(
                self._MIN_WHEEL_NOTCHES, self._wheel_notches - 1
            )
        elif fresh_ratio < 0.40:
            self._wheel_notches = min(
                self._MAX_WHEEL_NOTCHES, self._wheel_notches + 1
            )

    def _poll_manual_frame(self) -> None:
        if not self._vertical_ready(automatic=False):
            return
        if self._escape_pressed():
            self.cancel()
            return
        frame = self._capture_current_frame()
        if frame is None:
            return
        if self._manual_previous is not None and VerticalStitcher.frames_share_position(
            self._manual_previous, frame
        ):
            self._manual_stable_samples += 1
        else:
            self._manual_stable_samples = 0
        self._manual_previous = frame
        self._manual_frames.append(frame)
        if len(self._manual_frames) > self._MAX_TRANSITION_FRAMES:
            self._manual_frames.pop(0)
        if self._manual_stable_samples >= self._SETTLE_REQUIRED_SAMPLES:
            self._manual_stable_samples = 0
            transition_frames = self._manual_frames
            self._manual_frames = [frame]
            result = self._accept_stable_batch(transition_frames)
            if result == "appended":
                self.status_changed.emit(
                    f"手动拼接成功，当前长图 {self._stitcher.total_height} 像素"
                )
            elif result == "stationary":
                self._bottom_confirmations = 0
            else:
                self._pause_for_mismatch()
                return
        self._schedule(self._MANUAL_POLL_INTERVAL_MS, self._poll_manual_frame)

    def _capture_current_frame(self) -> QImage | None:
        try:
            if self._before_capture is not None:
                self._before_capture()
            return self._engine.capture_selection(
                self._virtual_geometry, self._selection
            )
        except Exception as error:
            self._finished = True
            self._schedule_generation += 1
            self.failed.emit(f"长截图失败：{error}")
            return None
        finally:
            if self._after_capture is not None and not self._finished:
                self._after_capture()

    def _mark_append(self) -> None:
        self._has_new_content = True
        self._bottom_confirmations = 0
        self._recovering_overlap = False

    def _pause_for_mismatch(self) -> None:
        if not self._automatic and self._recovering_overlap:
            self._schedule_generation += 1
            self._reset_manual_observation()
            self._restore_target_window()
            self._schedule(self._MANUAL_POLL_INTERVAL_MS, self._poll_manual_frame)
            return
        self._switch_to_manual(
            "拼接暂时失去重叠，手动恢复仍在采集；请向上滚动到有重叠的位置，"
            "再小幅向下滚动。到目标位置后按 F2 完成"
        )
        self._recovering_overlap = True

    def _pause_with_attention(self, message: str) -> None:
        self._automatic = False
        self._paused = True
        self._schedule_generation += 1
        self.automatic_mode_changed.emit(False)
        self.paused_changed.emit(True)
        self.attention_required.emit(message)

    def _switch_to_manual(self, message: str) -> None:
        self._automatic = False
        self._paused = False
        self._recovering_overlap = False
        self._schedule_generation += 1
        self._reset_manual_observation()
        self.automatic_mode_changed.emit(False)
        self.paused_changed.emit(False)
        self.attention_required.emit(message)
        self._restore_target_window()
        self._schedule(self._MANUAL_POLL_INTERVAL_MS, self._poll_manual_frame)

    def _reset_manual_observation(self) -> None:
        self._manual_previous = None
        self._manual_stable_samples = 0
        self._manual_frames = []

    def _vertical_ready(self, *, automatic: bool) -> bool:
        return (
            not self._finished
            and not self._paused
            and self._automatic is automatic
        )

    def _schedule(self, delay_ms: int, callback: Callable[[], None]) -> None:
        generation = self._schedule_generation

        def run_if_current() -> None:
            if generation == self._schedule_generation and not self._finished:
                callback()

        QTimer.singleShot(delay_ms, run_if_current)

    def _restore_target_window(self) -> None:
        if self._target_window:
            ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(self._target_window))

    def _escape_pressed(self) -> bool:
        """Detect a fresh Escape press even while the source window has focus."""
        down = bool(ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
        pressed = down and not self._escape_was_down
        self._escape_was_down = down
        return pressed
