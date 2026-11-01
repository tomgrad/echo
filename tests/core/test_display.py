import numpy as np
import pytest
from PySide6.QtGui import QImage

from echo_core.display import display_array, mono_levels, qimage_from_frame, thumbnail_qimage


def test_display_array_swaps_spatial_axes():
    # Same axes Echo used before the refactor: color swaps -3,-2; mono swaps -2,-1.
    assert display_array(np.zeros((8, 10)), False).shape == (10, 8)
    assert display_array(np.zeros((3, 8, 10)), False).shape == (3, 10, 8)
    assert display_array(np.zeros((8, 10, 3)), True).shape == (10, 8, 3)
    assert display_array(np.zeros((4, 8, 10, 3)), True).shape == (4, 10, 8, 3)


def test_mono_levels_are_percentiles():
    frames = np.arange(100, dtype=np.uint16).reshape(2, 5, 10)
    low, high = mono_levels(frames)
    assert low == pytest.approx(0.99)
    assert high == pytest.approx(98.01)


def test_mono_levels_expand_constant_frames():
    low, high = mono_levels(np.full((2, 4, 4), 7, dtype=np.uint16))
    assert high > low


def test_color_qimage_geometry_and_format():
    frame = np.zeros((8, 10, 3), dtype=np.uint8)
    image = qimage_from_frame(frame, None)
    assert image.format() == QImage.Format_RGB888
    assert (image.width(), image.height()) == (10, 8)


def test_mono_qimage_maps_levels_to_full_range():
    frame = np.array([[0, 100]], dtype=np.uint16)
    image = qimage_from_frame(frame, (0.0, 100.0))
    assert image.format() == QImage.Format_Grayscale8
    assert image.pixelColor(0, 0).red() == 0
    assert image.pixelColor(1, 0).red() == 255


def test_qimage_respects_row_stride_for_unaligned_widths():
    # Width 5: 15 bytes per RGB row and 5 per gray row, neither a multiple of 4.
    color = np.zeros((2, 5, 3), dtype=np.uint8)
    color[1, 0] = (10, 20, 30)
    pixel = qimage_from_frame(color, None).pixelColor(0, 1)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (10, 20, 30)

    mono = np.zeros((2, 5), dtype=np.uint16)
    mono[1, 0] = 100
    image = qimage_from_frame(mono, (0.0, 100.0))
    assert image.pixelColor(0, 1).red() == 255
    assert image.pixelColor(4, 0).red() == 0


def test_thumbnail_scales_to_requested_width():
    image = thumbnail_qimage(np.zeros((100, 200, 3), dtype=np.uint8), None, width=50)
    assert image.width() == 50
    assert image.height() == 25
