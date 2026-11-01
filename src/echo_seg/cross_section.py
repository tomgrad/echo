"""Geometry for the cross-section view: contour crossings and volume sampling."""
import numpy as np

LINE_AXES = {"custom"}  # cross-section modes defined by a line in the image


def contour_intersections_with_slice(contour, slice_index):
    pts = np.asarray(contour, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
        return []

    c = float(slice_index)
    intersections = []
    count = pts.shape[0]

    for i in range(count):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % count]

        # Slice line: x == c; result coordinate is y.
        if x1 == x2 == c:
            intersections.extend([float(y1), float(y2)])
            continue
        if x1 == x2:
            continue
        t = (c - x1) / (x2 - x1)
        if 0.0 <= t <= 1.0:
            intersections.append(float(y1 + t * (y2 - y1)))

    if not intersections:
        return []

    # Deduplicate near-identical points from shared vertices.
    rounded = np.round(np.asarray(intersections, dtype=float), 3)
    return np.unique(rounded).astype(float).tolist()

def _cross2d(a, b):
    return float(a[0] * b[1] - a[1] * b[0])

def contour_intersections_with_line_segment(contour, start_xy, end_xy):
    pts = np.asarray(contour, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 2:
        return []

    p0 = np.asarray(start_xy, dtype=float)
    p1 = np.asarray(end_xy, dtype=float)
    r = p1 - p0
    r_norm = float(np.linalg.norm(r))
    if r_norm < 1e-6:
        return []

    intersections = []
    count = pts.shape[0]
    eps = 1e-6

    for i in range(count):
        q = pts[i]
        q2 = pts[(i + 1) % count]
        s = q2 - q
        q_minus_p = q - p0
        r_cross_s = _cross2d(r, s)

        if abs(r_cross_s) <= eps:
            # Collinear edge: include edge endpoints that fall on the sampling line segment.
            if abs(_cross2d(q_minus_p, r)) > 1e-3:
                continue
            for candidate in (q, q2):
                t = float(np.dot(candidate - p0, r) / np.dot(r, r))
                if 0.0 <= t <= 1.0:
                    intersections.append(t * r_norm)
            continue

        t = _cross2d(q_minus_p, s) / r_cross_s
        u = _cross2d(q_minus_p, r) / r_cross_s
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            intersections.append(t * r_norm)

    if not intersections:
        return []

    rounded = np.round(np.asarray(intersections, dtype=float), 3)
    return np.unique(rounded).astype(float).tolist()

def sample_volume_along_segment(
    volume: np.ndarray,
    start_xy: np.ndarray,
    end_xy: np.ndarray,
    samples_count: int,
) -> np.ndarray:
    samples_count = max(2, int(samples_count))
    x = np.linspace(float(start_xy[0]), float(end_xy[0]), samples_count, dtype=float)
    y = np.linspace(float(start_xy[1]), float(end_xy[1]), samples_count, dtype=float)

    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, volume.shape[2] - 1)
    y1 = np.clip(y0 + 1, 0, volume.shape[1] - 1)
    x0 = np.clip(x0, 0, volume.shape[2] - 1)
    y0 = np.clip(y0, 0, volume.shape[1] - 1)

    wx = x - x0
    wy = y - y0

    v00 = volume[:, y0, x0]
    v10 = volume[:, y0, x1]
    v01 = volume[:, y1, x0]
    v11 = volume[:, y1, x1]

    top = v00 * (1.0 - wx) + v10 * wx
    bottom = v01 * (1.0 - wx) + v11 * wx
    return (top * (1.0 - wy) + bottom * wy).T


def cross_section_contour_points(
    contours_by_frame,
    frame_count,
    axis,
    slice_index,
    image_size,
    line_start=None,
    line_end=None,
    line_length=None,
    free_full_size=None,
    free_clip_offset=0.0,
):
    if contours_by_frame is None:
        return []

    points = []
    max_y = float(max(1, image_size))

    for frame_idx in range(frame_count):
        contours = contours_by_frame.get(frame_idx, [])
        for contour in contours:
            if axis in LINE_AXES:
                values = contour_intersections_with_line_segment(contour, line_start, line_end)
            else:
                values = contour_intersections_with_slice(contour, slice_index)
            for value in values:
                if axis in LINE_AXES and line_length is not None and line_length > 1e-6:
                    full_size = max(2, int(free_full_size if free_full_size is not None else image_size))
                    # Project arc-length along free line into full sampled row coordinates.
                    value = float(value) * float(full_size - 1) / float(line_length)
                    # Clip into displayed row coordinates when we crop to frame width.
                    value = float(value) - float(free_clip_offset)
                    y = float(np.clip(max_y - value, 0.0, max_y))
                else:
                    # Vertical slice rows are flipped (upside down), so row index maps directly.
                    y = float(np.clip(value, 0.0, max_y))
                points.append((float(frame_idx), y))
    return points
