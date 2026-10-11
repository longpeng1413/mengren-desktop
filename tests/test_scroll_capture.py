import ctypes
from types import SimpleNamespace

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from core.long_capture import scroll_input
from core.long_capture.scroll_capture import ScrollCaptureSession
from ui.long_capture_controls import LongCaptureControls
from ui.long_capture_frame import LongCaptureFrame


def _frame(start_row: int) -> QImage:
    image = QImage(180, 400, QImage.Format.Format_ARGB32)
    image.fill(QColor(30, 30, 30))
    for y in range(image.height()):
        if (start_row + y) % 13 > 6:
            continue
        for x in range(20, 150):
            if (x + start_row + y) % 7 < 3:
                image.setPixelColor(
                    x,
                    y,
                    QColor((start_row + y) % 256, ((start_row + y) * 3) % 256, 160),
                )
    return image


def test_long_capture_frame_places_its_border_outside_the_capture_selection() -> None:
    frame = LongCaptureFrame.frame_geometry(QRect(100, 200, 300, 400))

    assert frame == QRect(93, 193, 314, 414)


def test_escape_cancellation_discards_the_long_capture() -> None:
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )
    cancelled: list[bool] = []
    session.cancelled.connect(lambda: cancelled.append(True))

    session.cancel()

    assert session._finished
    assert cancelled == [True]


def test_automatic_batch_recovers_a_fast_scroll_from_transition_frames() -> None:
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )

    result = session._accept_stable_batch(
        [_frame(220), _frame(440), _frame(600)]
    )

    assert result == "appended"
    assert session._stitcher.total_height == 1000


def test_automatic_capture_finishes_after_five_stationary_scroll_attempts() -> None:
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )
    completed: list[QImage] = []
    session.completed.connect(completed.append)
    session._schedule = lambda *args: None
    assert session._accept_stable_batch([_frame(80)]) == "appended"

    for expected in (1, 2, 3, 4, 5):
        session._settle_frames = [_frame(80)]
        session._commit_auto_frames()
        assert session._bottom_confirmations == expected
        assert bool(completed) is (expected == 5)

    assert len(completed) == 1
    assert completed[0].height() == 480


def test_ignored_automatic_wheel_switches_to_manual_instead_of_finishing() -> None:
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )
    warnings: list[str] = []
    completed: list[QImage] = []
    session.attention_required.connect(warnings.append)
    session.completed.connect(completed.append)
    session._schedule = lambda *args: None

    for _ in range(5):
        session._settle_frames = [_frame(0)]
        session._commit_auto_frames()

    assert not completed
    assert not session.automatic
    assert warnings and "未检测到自动滚动" in warnings[0]


def test_unrecoverable_gap_keeps_manual_recovery_active() -> None:
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )
    warnings: list[str] = []
    session.attention_required.connect(warnings.append)
    session._settle_frames = [_frame(600)]
    scheduled: list[object] = []
    session._schedule = lambda _delay, callback: scheduled.append(callback)

    session._commit_auto_frames()

    assert not session.paused
    assert not session.automatic
    assert scheduled and scheduled[-1].__name__ == "_poll_manual_frame"
    assert warnings and "手动恢复仍在采集" in warnings[0]


def test_continuously_moving_page_pauses_instead_of_stitching_unstable_frame() -> None:
    class FakeEngine:
        def capture_selection(self, geometry, selection):
            return _frame(80)

    session = ScrollCaptureSession(
        FakeEngine(),
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )
    warnings: list[str] = []
    session.attention_required.connect(warnings.append)
    session._settle_frames = [_frame(0)] * (session._SETTLE_MAX_SAMPLES - 1)
    session._settle_stable_samples = 0

    session._collect_auto_sample()

    assert session.paused
    assert session._stitcher.total_height == 400
    assert warnings and "持续变化" in warnings[0]


def test_manual_mode_also_uses_transition_frames_after_wheel_scrolling() -> None:
    frames = [_frame(220), _frame(440), _frame(600), _frame(600), _frame(600)]

    class FakeEngine:
        def capture_selection(self, geometry, selection):
            return frames.pop(0)

    session = ScrollCaptureSession(
        FakeEngine(),
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )
    session._automatic = False
    session._schedule = lambda *args: None

    for _ in range(5):
        session._poll_manual_frame()

    assert session._stitcher.total_height == 1000
    assert not session.paused


def test_automatic_step_targets_selection_center_and_scrolls_down() -> None:
    calls: list[tuple[int, int, int]] = []
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 300, 500),
        QRect(20, 40, 180, 400),
        _frame(0),
        0,
        scroll_handler=lambda x, y, notches: not calls.append((x, y, notches)),
    )
    session._schedule = lambda *args: None

    session._begin_auto_step()

    assert calls == [(109, 239, -4)]


def test_bottom_probes_use_small_steps_at_multiple_safe_points() -> None:
    calls: list[tuple[int, int, int]] = []
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 300, 500),
        QRect(20, 40, 180, 400),
        _frame(0),
        0,
        scroll_handler=lambda x, y, notches: not calls.append((x, y, notches)),
    )
    session._schedule = lambda *args: None

    for confirmations in (1, 2, 3, 4):
        session._bottom_confirmations = confirmations
        session._begin_auto_step()

    assert calls == [
        (42, 239, -1),
        (177, 239, -1),
        (42, 173, -1),
        (177, 306, -1),
    ]


def test_automatic_scroll_accelerates_without_removing_stability_checks() -> None:
    session = ScrollCaptureSession(
        None,
        QRect(0, 0, 180, 400),
        QRect(0, 0, 180, 400),
        _frame(0),
        0,
    )

    assert session._wheel_notches == 4
    assert session._stitcher.append(_frame(80))

    session._adapt_scroll_step()

    assert session._wheel_notches == 5
    assert session._MAX_WHEEL_NOTCHES == 5
    assert session._SETTLE_REQUIRED_SAMPLES == 2
    assert session._NEXT_STEP_DELAY_MS <= 100


def test_windows_wheel_driver_uses_discrete_send_input(monkeypatch) -> None:
    calls: list[tuple[str, int, int | None]] = []

    class FakeUser32:
        def SetCursorPos(self, x, y):
            calls.append(("cursor", x, y))
            return True

        def SendInput(self, count, pointer, size):
            calls.append(("input", count, size))
            return count

    monkeypatch.setattr(scroll_input.sys, "platform", "win32")
    monkeypatch.setattr(
        scroll_input.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
        raising=False,
    )

    assert scroll_input.send_vertical_wheel(100, 200, -3)
    assert calls[0] == ("cursor", 100, 200)
    assert calls[1][0] == "input"


def test_windows_wheel_driver_normalizes_one_line_setting(monkeypatch) -> None:
    wheel_values: list[int] = []
    input_counts: list[int] = []

    class FakeUser32:
        def SystemParametersInfoW(self, action, parameter, output, flags):
            assert action == scroll_input._SPI_GETWHEELSCROLLLINES
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint)).contents.value = 1
            return True

        def SetCursorPos(self, x, y):
            return True

        def SendInput(self, count, pointer, size):
            event = ctypes.cast(
                pointer,
                ctypes.POINTER(scroll_input._Input),
            ).contents
            input_counts.append(count)
            wheel_values.append(int(event.mi.mouseData))
            return count

    monkeypatch.setattr(scroll_input.sys, "platform", "win32")
    monkeypatch.setattr(
        scroll_input.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
        raising=False,
    )

    assert scroll_input.send_vertical_wheel(100, 200, -4)
    assert input_counts == [1] * 12
    assert wheel_values == [ctypes.c_uint32(-120).value] * 12


def test_windows_wheel_driver_stops_when_a_discrete_event_is_rejected(monkeypatch) -> None:
    attempts: list[int] = []

    class FakeUser32:
        def SystemParametersInfoW(self, action, parameter, output, flags):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_uint)).contents.value = 1
            return True

        def SetCursorPos(self, x, y):
            return True

        def SendInput(self, count, pointer, size):
            attempts.append(count)
            return 0 if len(attempts) == 4 else 1

    monkeypatch.setattr(scroll_input.sys, "platform", "win32")
    monkeypatch.setattr(
        scroll_input.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32()),
        raising=False,
    )

    assert not scroll_input.send_vertical_wheel(100, 200, -4)
    assert attempts == [1, 1, 1, 1]


def test_wheel_normalization_handles_any_line_count() -> None:
    normalize = scroll_input._normalized_wheel_delta

    assert normalize(-4, 1) == -1440
    assert normalize(-4, 2) == -720
    assert normalize(-4, 3) == -480
    assert normalize(-4, 4) == -360
    assert normalize(-4, 5) == -288
    assert normalize(-4, 6) == -240
    assert normalize(-4, 7) == -206
    assert normalize(-4, scroll_input._WHEEL_PAGESCROLL) == -120


def test_normalized_delta_is_split_into_standard_detents_and_small_remainder() -> None:
    split = scroll_input._wheel_event_deltas

    assert split(-4, 1) == (-120,) * 12
    assert split(-4, 2) == (-120,) * 6
    assert split(-4, 3) == (-120,) * 4
    assert split(-4, 4) == (-120,) * 3
    assert split(-4, 5) == (-120, -120, -48)
    assert split(-4, 7) == (-120, -86)


def test_wheel_normalization_stays_near_baseline_for_all_windows_values() -> None:
    expected_line_units = 4 * 120 * 3

    for scroll_lines in range(1, 101):
        delta = abs(scroll_input._normalized_wheel_delta(-4, scroll_lines))
        actual_line_units = delta * scroll_lines
        assert abs(actual_line_units - expected_line_units) <= scroll_lines // 2 + 1


def test_long_capture_controls_expose_safe_manual_completion() -> None:
    _application = QApplication.instance() or QApplication([])
    controls = LongCaptureControls(QRect(20, 40, 300, 400))
    modes: list[bool] = []
    finished: list[bool] = []
    controls.automatic_mode_requested.connect(modes.append)
    controls.finish_requested.connect(lambda: finished.append(True))

    controls.mode_button.click()
    controls.finish_button.click()

    assert modes == [False]
    assert finished == [True]
    assert controls.finish_button.text() == "完成（F2）"
    controls.close()
