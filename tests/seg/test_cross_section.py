import numpy as np
import pytest

from echo_seg.cross_section import (
    contour_intersections_with_line_segment,
    contour_intersections_with_slice,
    cross_section_contour_points,
    sample_volume_along_segment,
)

SQUARE = [[2, 2], [8, 2], [8, 6], [2, 6]]


def test_slice_intersections_of_square():
    assert contour_intersections_with_slice(SQUARE, 5) == [2.0, 6.0]
    assert contour_intersections_with_slice(SQUARE, 20) == []


def test_slice_ignores_degenerate_contour():
    assert contour_intersections_with_slice([[1, 1]], 1) == []


def test_line_segment_intersections_are_arc_lengths():
    assert contour_intersections_with_line_segment(SQUARE, (0, 4), (10, 4)) == [2.0, 8.0]
    assert contour_intersections_with_line_segment(SQUARE, (0, 4), (0, 4)) == []


def test_sample_volume_interpolates_between_pixels():
    volume = np.zeros((2, 3, 3), dtype=float)
    volume[:, :, 1] = 10.0
    out = sample_volume_along_segment(volume, np.array([0.0, 0.0]), np.array([2.0, 0.0]), 5)
    assert out.shape == (5, 2)
    assert out[1, 0] == pytest.approx(5.0)
    assert out[2, 0] == pytest.approx(10.0)


def test_contour_points_vertical_slice():
    contours = {0: [np.array(SQUARE)], 2: [np.array(SQUARE)]}
    points = cross_section_contour_points(contours, 3, "vertical", 5, 10)
    assert sorted(points) == [(0.0, 2.0), (0.0, 6.0), (2.0, 2.0), (2.0, 6.0)]
    assert cross_section_contour_points(None, 3, "vertical", 5, 10) == []
