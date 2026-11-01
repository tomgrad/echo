import json

import numpy as np
import pytest

from echo_core.masks import (
    build_custom_mask,
    contours_from_jsonable,
    contours_to_jsonable,
    find_external_contours,
    fit_spline_contours,
    fix_labeled_mask,
    interpolate_contour_catmull_rom,
    point_segment_distance_sq,
    sample_outline_curve,
)


def _square_volume(frames=2):
    mask = np.zeros((frames, 20, 20), dtype=np.uint16)
    mask[:, 5:15, 5:15] = 1
    return mask


def test_fix_labeled_mask_level_zero_keeps_mask():
    mask = _square_volume()
    fixed = fix_labeled_mask(mask, iterations=0)
    assert np.array_equal(fixed == 1, mask == 1)


def test_fix_labeled_mask_level_zero_fills_holes():
    mask = _square_volume(frames=1)
    mask[0, 9:11, 9:11] = 0
    fixed = fix_labeled_mask(mask, iterations=0)
    assert np.all(fixed[0, 5:15, 5:15] == 1)


def test_fix_labeled_mask_erodes_with_positive_level():
    mask = _square_volume(frames=1)
    fixed = fix_labeled_mask(mask, iterations=1)
    assert (fixed == 1).sum() < (mask == 1).sum()
    assert (fixed == 1).sum() > 0


def test_fix_labeled_mask_keeps_object_ids_separate():
    mask = np.zeros((1, 20, 20), dtype=np.uint16)
    mask[0, 2:8, 2:8] = 1
    mask[0, 12:18, 12:18] = 2
    fixed = fix_labeled_mask(mask, iterations=0)
    assert set(np.unique(fixed)) == {0, 1, 2}


def test_fix_labeled_mask_rejects_bad_shape():
    with pytest.raises(ValueError):
        fix_labeled_mask(np.zeros((2, 2, 2, 2), dtype=np.uint16), iterations=1)


def test_find_external_contours_per_frame():
    mask = _square_volume(frames=3)
    contours = find_external_contours(mask, epsilon=0.0)
    assert sorted(contours) == [0, 1, 2]
    for frame_contours in contours.values():
        assert len(frame_contours) == 1
        pts = frame_contours[0]
        assert pts.shape[1] == 2
        assert pts[:, 0].min() == 5 and pts[:, 0].max() == 14


def test_find_external_contours_keeps_labels_above_255():
    mask = np.zeros((1, 20, 20), dtype=np.uint16)
    mask[0, 5:15, 5:15] = 300
    contours = find_external_contours(mask, epsilon=0.0)
    assert len(contours[0]) == 1


def test_find_external_contours_rejects_bad_shape():
    with pytest.raises(ValueError):
        find_external_contours(np.zeros((2, 2, 2, 2)), epsilon=0.0)


def test_catmull_rom_passes_near_control_points():
    angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    circle = np.stack([np.cos(angles), np.sin(angles)], axis=1) * 10
    out = interpolate_contour_catmull_rom(circle, num_control_points=16, num_samples=160)
    radii = np.linalg.norm(out, axis=1)
    assert out.shape == (160, 2)
    assert np.allclose(radii, 10, atol=0.5)


def test_catmull_rom_input_validation():
    with pytest.raises(ValueError):
        interpolate_contour_catmull_rom(np.zeros((3, 2)), num_control_points=4)
    with pytest.raises(ValueError):
        interpolate_contour_catmull_rom(np.zeros((8, 2)), num_control_points=3)


def test_fit_spline_contours_keeps_short_contours():
    short = np.array([[0, 0], [1, 0], [1, 1]], dtype=float)
    splines, nodes = fit_spline_contours({0: [short]}, num_control_points=4, return_nodes=True)
    assert np.array_equal(splines[0][0], short)
    assert np.array_equal(nodes[0][0], short)


def test_sample_outline_curve_requires_four_vertices():
    with pytest.raises(ValueError):
        sample_outline_curve([[0, 0], [1, 1], [2, 2]])


def test_point_segment_distance_sq():
    assert point_segment_distance_sq((0, 1), (-1, 0), (1, 0)) == pytest.approx(1.0)
    assert point_segment_distance_sq((3, 4), (0, 0), (0, 0)) == pytest.approx(25.0)


def test_build_custom_mask_fills_square_outline():
    outline = [[5, 5], [15, 5], [15, 15], [5, 15]]
    mask = build_custom_mask(outline, height=20, width=20)
    assert mask.shape == (20, 20)
    assert mask[10, 10] == 1
    assert mask[0, 0] == 0
    assert mask.sum() > 50


def test_contours_json_round_trip_keeps_frames_and_points():
    contours = find_external_contours(_square_volume(frames=3), epsilon=0.0)
    text = json.dumps(contours_to_jsonable(contours))
    restored = contours_from_jsonable(json.loads(text))
    assert sorted(restored) == [0, 1, 2]
    for frame_idx in contours:
        assert len(restored[frame_idx]) == len(contours[frame_idx])
        assert np.array_equal(restored[frame_idx][0], contours[frame_idx][0])
