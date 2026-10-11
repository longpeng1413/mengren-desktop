"""Fast and tolerant vertical image stitching for automated scroll capture."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from PySide6.QtGui import QImage, QPainter


@dataclass(frozen=True, slots=True)
class Match:
    """A verified overlap between two successive scroll frames."""

    overlap: int
    average_error: float
    meaningful_samples: int


class VerticalStitcher:
    """Accumulates proven frame segments and renders the full image only once."""

    _MIN_OVERLAP_PIXELS = 80
    _MIN_OVERLAP_RATIO = 0.28
    _MAX_ERROR = 45.0
    _SAME_FRAME_ERROR = 1.0
    _MIN_MEANINGFUL_SAMPLES = 36
    _DARK_PIXEL_LIMIT = 52
    _X_SAMPLES = 56
    _Y_SAMPLES = 36
    _COARSE_SHIFT_STEP = 4
    _REFINE_RADIUS = 5
    _STATIONARY_MAX_ERROR = 8.0
    _STATIONARY_DIFFERENCE_CAP = 40
    _TRANSLATION_MIN_RESPONSE = 0.14
    _TRANSLATION_MIN_VERTICAL_PIXELS = 1.5
    _TRANSLATION_MAX_HORIZONTAL_RATIO = 0.08
    _TRANSLATION_MIN_CLIPPED_ERROR = 0.35
    _DENSE_NEAR_BEST_ERROR = 0.75
    _DIRECT_DENSE_MAX_ERROR = 2.0

    def __init__(self, first_frame: QImage) -> None:
        first_frame = first_frame.convertToFormat(QImage.Format.Format_ARGB32)
        self._segments = [first_frame]
        self._total_height = first_frame.height()
        self._previous = first_frame
        self._rendered: QImage | None = None
        self._last_match: Match | None = None

    @property
    def last_match(self) -> Match | None:
        """Return the overlap accepted by the most recent append attempt."""
        return self._last_match

    @property
    def total_height(self) -> int:
        """Return accumulated height without rendering the full long image."""
        return self._total_height

    @property
    def image(self) -> QImage:
        """Render and return the completed long screenshot on demand."""
        if self._rendered is None:
            result = QImage(
                self._previous.width(),
                self._total_height,
                QImage.Format.Format_ARGB32,
            )
            result.fill(0)
            painter = QPainter(result)
            try:
                offset = 0
                for segment in self._segments:
                    painter.drawImage(0, offset, segment)
                    offset += segment.height()
            finally:
                painter.end()
            self._rendered = result
        return self._rendered

    def append(self, frame: QImage) -> bool:
        """Append only the non-overlapping rows after a verified seam match."""
        self._last_match = None
        frame = frame.convertToFormat(QImage.Format.Format_ARGB32)
        if frame.size() != self._previous.size():
            raise ValueError("Long capture frames must have identical dimensions.")

        match = self._find_match(self._previous, frame)
        if match is None or match.average_error > self._MAX_ERROR:
            return False

        fresh_height = frame.height() - match.overlap
        if fresh_height <= 0:
            return False

        self._segments.append(frame.copy(0, match.overlap, frame.width(), fresh_height))
        self._total_height += fresh_height
        self._rendered = None
        self._previous = frame
        self._last_match = match
        return True

    def is_same_as_previous(self, frame: QImage) -> bool:
        """Return True only when scrolling produced no visible new content."""
        frame = frame.convertToFormat(QImage.Format.Format_ARGB32)
        if frame.size() != self._previous.size():
            return False

        previous = self._previous.constBits()
        current = frame.constBits()
        stride = self._previous.bytesPerLine()
        width = self._previous.width()
        height = self._previous.height()
        total = 0
        samples = 0
        for y_index in range(32):
            y = (y_index + 1) * height // 33
            for x_index in range(32):
                x = int(width * 0.20) + (x_index + 1) * int(width * 0.75) // 33
                offset = y * stride + x * 4
                total += abs(previous[offset] - current[offset])
                total += abs(previous[offset + 1] - current[offset + 1])
                total += abs(previous[offset + 2] - current[offset + 2])
                samples += 3
        return total / samples <= self._SAME_FRAME_ERROR

    def is_same_position(self, frame: QImage) -> bool:
        """Tolerate small local animation while detecting a stationary viewport."""
        return self.frames_share_position(self._previous, frame)

    @classmethod
    def frames_share_position(cls, first: QImage, second: QImage) -> bool:
        """Return whether two frames show the same overall scroll position.

        A downscaled central document area prevents a blinking caret, cursor,
        scrollbar, or small animation from defeating bottom/stability detection.
        """
        first = first.convertToFormat(QImage.Format.Format_ARGB32)
        second = second.convertToFormat(QImage.Format.Format_ARGB32)
        if first.size() != second.size() or first.isNull():
            return False
        width = first.width()
        height = first.height()
        left = int(width * 0.05)
        right = max(left + 1, int(width * 0.95))
        target_width = min(180, max(48, (right - left) // 4))
        target_height = min(360, max(80, height // 2))
        first_gray = cls._compact_gray(
            first, left, right, target_width, target_height
        )
        second_gray = cls._compact_gray(
            second, left, right, target_width, target_height
        )
        difference = cv2.absdiff(first_gray, second_gray)
        clipped_error = float(
            np.mean(np.minimum(difference, cls._STATIONARY_DIFFERENCE_CAP))
        )
        first_edges = cv2.Sobel(first_gray, cv2.CV_32F, 0, 1, ksize=3)
        second_edges = cv2.Sobel(second_gray, cv2.CV_32F, 0, 1, ksize=3)
        (shift_x, shift_y), response = cv2.phaseCorrelate(
            first_edges,
            second_edges,
        )
        if (
            response >= cls._TRANSLATION_MIN_RESPONSE
            and abs(shift_y) >= cls._TRANSLATION_MIN_VERTICAL_PIXELS
            and abs(shift_x)
            <= target_width * cls._TRANSLATION_MAX_HORIZONTAL_RATIO
            and clipped_error >= cls._TRANSLATION_MIN_CLIPPED_ERROR
        ):
            return False
        return clipped_error <= cls._STATIONARY_MAX_ERROR

    def _find_match(self, previous: QImage, current: QImage) -> Match | None:
        height = previous.height()
        minimum_overlap = max(
            self._MIN_OVERLAP_PIXELS,
            int(height * self._MIN_OVERLAP_RATIO),
        )
        if height <= minimum_overlap:
            return None

        phase_match = self._find_phase_match(previous, current, minimum_overlap)
        if phase_match is not None:
            estimated_shift = height - phase_match.overlap
            refined = self._best_candidate(
                previous.constBits(),
                current.constBits(),
                previous.bytesPerLine(),
                previous.width(),
                range(
                    max(1, estimated_shift - self._REFINE_RADIUS),
                    min(height - minimum_overlap, estimated_shift + self._REFINE_RADIUS) + 1,
                ),
                height,
                minimum_meaningful_samples=8,
            )
            if refined is not None and refined.average_error <= self._MAX_ERROR:
                return refined
            if phase_match.average_error <= self._DIRECT_DENSE_MAX_ERROR:
                return phase_match

        dense_match = self._find_dense_match(previous, current, minimum_overlap)
        if dense_match is not None and dense_match.average_error <= self._MAX_ERROR:
            estimated_shift = height - dense_match.overlap
            refined = self._best_candidate(
                previous.constBits(),
                current.constBits(),
                previous.bytesPerLine(),
                previous.width(),
                range(
                    max(1, estimated_shift - self._REFINE_RADIUS * 2),
                    min(height - minimum_overlap, estimated_shift + self._REFINE_RADIUS * 2) + 1,
                ),
                height,
            )
            if refined is not None and refined.average_error <= self._MAX_ERROR:
                return refined
            if dense_match.average_error <= self._DIRECT_DENSE_MAX_ERROR:
                return dense_match

        previous_bytes = previous.constBits()
        current_bytes = current.constBits()
        stride = previous.bytesPerLine()
        width = previous.width()
        maximum_shift = height - minimum_overlap

        coarse_shifts = [1, *range(self._COARSE_SHIFT_STEP, maximum_shift + 1, self._COARSE_SHIFT_STEP)]
        best = self._best_candidate(
            previous_bytes,
            current_bytes,
            stride,
            width,
            coarse_shifts,
            height,
        )
        if best is None:
            return None

        best_shift = height - best.overlap
        refined_start = max(1, best_shift - self._REFINE_RADIUS)
        refined_end = min(maximum_shift, best_shift + self._REFINE_RADIUS)
        refined = self._best_candidate(
            previous_bytes,
            current_bytes,
            stride,
            width,
            range(refined_start, refined_end + 1),
            height,
        )
        return refined or best

    def _find_phase_match(
        self,
        previous: QImage,
        current: QImage,
        minimum_overlap: int,
    ) -> Match | None:
        """Estimate a downward document scroll without being biased by blank rows."""
        height = previous.height()
        width = previous.width()
        left = int(width * 0.05)
        right = max(left + 1, int(width * 0.95))
        target_width = min(180, max(72, (right - left) // 4))
        # Preserve the original vertical resolution so a confirmed translation
        # does not introduce one- or two-row seams on sparse documents.
        target_height = height
        previous_gray = self._compact_gray(
            previous, left, right, target_width, target_height
        )
        current_gray = self._compact_gray(
            current, left, right, target_width, target_height
        )
        previous_edges = cv2.Sobel(previous_gray, cv2.CV_32F, 0, 1, ksize=3)
        current_edges = cv2.Sobel(current_gray, cv2.CV_32F, 0, 1, ksize=3)
        (shift_x, shift_y), response = cv2.phaseCorrelate(
            previous_edges,
            current_edges,
        )
        if (
            response < self._TRANSLATION_MIN_RESPONSE
            or shift_y > -self._TRANSLATION_MIN_VERTICAL_PIXELS
            or abs(shift_x) > target_width * self._TRANSLATION_MAX_HORIZONTAL_RATIO
        ):
            return None

        scale_y = target_height / height
        maximum_shift = height - minimum_overlap
        original_shift = max(1, min(maximum_shift, round(abs(shift_y) / scale_y)))
        scaled_shift = max(1, min(target_height - 1, round(original_shift * scale_y)))
        overlap = target_height - scaled_shift
        average_error = float(
            cv2.mean(
                cv2.absdiff(
                    previous_gray[scaled_shift:, :],
                    current_gray[:overlap, :],
                )
            )[0]
        )
        return Match(
            height - original_shift,
            average_error,
            target_width * overlap,
        )

    def _find_dense_match(
        self,
        previous: QImage,
        current: QImage,
        minimum_overlap: int,
    ) -> Match | None:
        """Estimate vertical movement from the full image area using fast native code."""
        height = previous.height()
        width = previous.width()
        if height <= minimum_overlap or width <= 1:
            return None

        left = int(width * 0.05)
        right = max(left + 1, int(width * 0.95))
        target_width = min(180, max(72, (right - left) // 4))
        target_height = min(360, max(100, height // 2))
        previous_gray = self._compact_gray(previous, left, right, target_width, target_height)
        current_gray = self._compact_gray(current, left, right, target_width, target_height)
        scale_y = target_height / height
        minimum_overlap_scaled = max(20, round(minimum_overlap * scale_y))
        maximum_shift = target_height - minimum_overlap_scaled
        if maximum_shift < 1:
            return None

        errors: list[tuple[float, int]] = []
        for shift in range(1, maximum_shift + 1):
            overlap = target_height - shift
            error = float(cv2.mean(cv2.absdiff(previous_gray[shift:, :], current_gray[:overlap, :]))[0])
            errors.append((error, shift))

        best_error = min(error for error, _shift in errors)
        # Sparse documents often repeat headings and blank gaps. Several shifts
        # can therefore be almost equally good; the smallest near-best shift is
        # the only choice that cannot silently skip an intermediate section.
        if best_error <= 2.0:
            best_shift = min(
                shift
                for error, shift in errors
                if error <= best_error + self._DENSE_NEAR_BEST_ERROR
            )
        else:
            best_shift = min(
                shift for error, shift in errors if error == best_error
            )
        selected_error = next(
            error for error, shift in errors if shift == best_shift
        )

        original_shift = max(1, min(height - minimum_overlap, round(best_shift / scale_y)))
        return Match(
            height - original_shift,
            selected_error,
            target_width * (target_height - best_shift),
        )

    @staticmethod
    def _compact_gray(
        image: QImage,
        left: int,
        right: int,
        target_width: int,
        target_height: int,
    ) -> np.ndarray:
        """Create a small grayscale view for robust whole-image movement matching."""
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            image.height(),
            image.bytesPerLine() // 4,
            4,
        )
        color = pixels[:, left:right, :3]
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (target_width, target_height), interpolation=cv2.INTER_AREA)

    def _best_candidate(
        self,
        previous: memoryview,
        current: memoryview,
        stride: int,
        width: int,
        shifts,
        height: int,
        minimum_meaningful_samples: int | None = None,
    ) -> Match | None:
        """Return the lowest-error overlap among a limited shift candidate set."""
        required_samples = (
            self._MIN_MEANINGFUL_SAMPLES
            if minimum_meaningful_samples is None
            else minimum_meaningful_samples
        )
        best: Match | None = None
        for shift in shifts:
            overlap = height - shift
            error, samples = self._sample_error(previous, current, stride, width, shift, overlap)
            if samples < required_samples:
                continue
            candidate = Match(overlap, error, samples)
            if (
                best is None
                or candidate.average_error < best.average_error
                or (
                    candidate.average_error == best.average_error
                    and candidate.overlap > best.overlap
                )
            ):
                best = candidate
        return best

    def _sample_error(
        self,
        previous: memoryview,
        current: memoryview,
        stride: int,
        width: int,
        shift: int,
        overlap: int,
    ) -> tuple[float, int]:
        total = 0
        samples = 0
        horizontal_margin = int(width * 0.20)
        usable_width = max(1, int(width * 0.75))
        for y_index in range(self._Y_SAMPLES):
            y = (y_index + 1) * overlap // (self._Y_SAMPLES + 1)
            for x_index in range(self._X_SAMPLES):
                x = horizontal_margin + (x_index + 1) * usable_width // (self._X_SAMPLES + 1)
                previous_offset = (y + shift) * stride + x * 4
                current_offset = y * stride + x * 4
                previous_brightness = max(previous[previous_offset : previous_offset + 3])
                current_brightness = max(current[current_offset : current_offset + 3])
                if (
                    previous_brightness < self._DARK_PIXEL_LIMIT
                    and current_brightness < self._DARK_PIXEL_LIMIT
                ):
                    continue
                total += abs(previous[previous_offset] - current[current_offset])
                total += abs(previous[previous_offset + 1] - current[current_offset + 1])
                total += abs(previous[previous_offset + 2] - current[current_offset + 2])
                samples += 3
        if not samples:
            return float("inf"), 0
        return total / samples, samples // 3
