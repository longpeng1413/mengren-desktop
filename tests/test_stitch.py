from PySide6.QtGui import QColor, QImage

from core.long_capture.stitch import VerticalStitcher


def _frame(start_row: int) -> QImage:
    image = QImage(180, 400, QImage.Format.Format_ARGB32)
    image.fill(QColor(30, 30, 30))
    for y in range(image.height()):
        if (start_row + y) % 13 > 6:
            continue
        for x in range(20, 150):
            if (x + start_row + y) % 7 < 3:
                color = QColor(
                    (start_row + y) % 256,
                    ((start_row + y) * 3) % 256,
                    160,
                )
                image.setPixelColor(x, y, color)
    return image


def test_stitcher_appends_only_new_rows_on_a_dark_document() -> None:
    stitcher = VerticalStitcher(_frame(0))

    assert stitcher.append(_frame(80))
    assert stitcher.image.height() == 480


def test_stitcher_accepts_a_larger_fast_scroll_step() -> None:
    stitcher = VerticalStitcher(_frame(0))

    assert stitcher.append(_frame(220))
    assert stitcher.image.height() == 620


def test_stitcher_rejects_a_non_overlapping_frame() -> None:
    stitcher = VerticalStitcher(_frame(0))

    assert not stitcher.append(_frame(600))


def test_stitcher_recognizes_an_unchanged_frame() -> None:
    frame = _frame(0)
    stitcher = VerticalStitcher(frame)

    assert stitcher.is_same_as_previous(frame)


def test_stationary_detection_ignores_one_small_dynamic_region() -> None:
    frame = _frame(0)
    changed = frame.copy()
    for y in range(20, 120):
        for x in range(20, 80):
            changed.setPixelColor(x, y, QColor(255, 80, 40))
    stitcher = VerticalStitcher(frame)

    assert stitcher.is_same_position(changed)


def test_stationary_detection_does_not_treat_a_large_jump_as_the_bottom() -> None:
    stitcher = VerticalStitcher(_frame(0))

    assert not stitcher.is_same_position(_frame(600))


def _sparse_dark_frame(start_row: int) -> QImage:
    image = QImage(360, 700, QImage.Format.Format_ARGB32)
    image.fill(QColor(24, 24, 24))
    for world_y in range(start_row, start_row + image.height()):
        line_offset = world_y % 180
        if line_offset not in {0, 1, 2, 36, 37}:
            continue
        y = world_y - start_row
        width = 250 if line_offset < 3 else 190
        for x in range(28, 28 + width):
            if (x + world_y) % 11 != 0:
                image.setPixelColor(x, y, QColor(235, 235, 235))
    return image


def test_stationary_detection_recognizes_sparse_dark_document_scroll() -> None:
    first = _sparse_dark_frame(0)
    scrolled = _sparse_dark_frame(150)

    assert not VerticalStitcher.frames_share_position(first, scrolled)


def test_sparse_dark_document_uses_the_true_scroll_distance() -> None:
    stitcher = VerticalStitcher(_sparse_dark_frame(0))

    assert stitcher.append(_sparse_dark_frame(150))
    assert stitcher.last_match is not None
    assert stitcher.last_match.overlap == 550
    assert stitcher.total_height == 850

