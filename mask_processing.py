import cv2
import numpy as np
from scipy import ndimage


def get_object_ids(mask: np.ndarray) -> list[int]:
    """Return sorted non-zero object ids from a labeled mask."""
    return [int(v) for v in np.unique(mask) if int(v) > 0]


def _fix_single_binary_mask(mask_2d: np.ndarray, iterations: int) -> np.ndarray:
    fixed = ndimage.binary_fill_holes(mask_2d)
    fixed = ndimage.binary_erosion(fixed, iterations=iterations)
    fixed = ndimage.binary_dilation(fixed, iterations=iterations)
    return fixed.astype(np.uint8)


def fix_labeled_mask(mask: np.ndarray, iterations: int, progress_callback=None) -> np.ndarray:
    """Fix each object mask and merge them back to a single labeled mask.

    Args:
        mask: Labeled segmentation mask, shape (H, W) or (T, H, W).
        iterations: Number of erosion/dilation iterations.
        progress_callback: Optional callback(done, total).
    """
    mask = np.asarray(mask).astype(np.uint16)
    obj_ids = get_object_ids(mask)

    if mask.ndim == 2:
        fixed_mask = np.zeros_like(mask, dtype=np.uint16)
        total = max(1, len(obj_ids))
        if progress_callback is not None:
            progress_callback(0, total)
        for idx, obj_id in enumerate(obj_ids, start=1):
            obj_fixed = _fix_single_binary_mask(mask == obj_id, iterations).astype(bool)
            write_here = obj_fixed & ((fixed_mask == 0) | (obj_id < fixed_mask))
            fixed_mask[write_here] = obj_id
            if progress_callback is not None:
                progress_callback(idx, total)
        return fixed_mask

    if mask.ndim == 3:
        fixed_mask = np.zeros_like(mask, dtype=np.uint16)
        total = mask.shape[0] * max(1, len(obj_ids))
        done = 0
        for frame_idx in range(mask.shape[0]):
            for obj_id in obj_ids:
                obj_fixed = _fix_single_binary_mask(mask[frame_idx] == obj_id, iterations).astype(bool)
                frame_out = fixed_mask[frame_idx]
                write_here = obj_fixed & ((frame_out == 0) | (obj_id < frame_out))
                frame_out[write_here] = obj_id
                fixed_mask[frame_idx] = frame_out
                done += 1
                if progress_callback is not None:
                    progress_callback(done, total)
        return fixed_mask

    raise ValueError(f"Unsupported mask shape: {mask.shape}")


def _extract_contours_from_frame(mask_2d: np.ndarray, epsilon: float, use_approx: bool) -> list[np.ndarray]:
    frame_mask = (mask_2d > 0).astype(np.uint8)
    found = cv2.findContours(frame_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = found[0] if len(found) == 2 else found[1]
    out = []
    for contour in contours:
        if use_approx:
            contour = cv2.approxPolyDP(contour, epsilon, True)
        pts = contour.reshape(-1, 2)
        if pts.shape[0] > 1:
            out.append(pts)
    return out


def find_external_contours(mask: np.ndarray, epsilon: float = 0.0) -> dict[int, list[np.ndarray]]:
    """Extract external contours from a mask volume.

    Returns:
        Dict mapping frame index to list of contour point arrays.
    """
    mask = np.asarray(mask).astype(np.uint8)
    contour_map: dict[int, list[np.ndarray]] = {}
    use_approx = float(epsilon) > 0.0

    if mask.ndim == 2:
        contour_map[0] = _extract_contours_from_frame(mask, float(epsilon), use_approx)
        return contour_map

    if mask.ndim == 3:
        for frame_idx in range(mask.shape[0]):
            contour_map[frame_idx] = _extract_contours_from_frame(mask[frame_idx], float(epsilon), use_approx)
        return contour_map

    raise ValueError(f"Unsupported mask shape: {mask.shape}")


def interpolate_contour_catmull_rom(
    contour: np.ndarray,
    num_control_points: int,
    num_samples: int = 400,
    return_control_points: bool = False,
):
    """Interpolate a contour with Catmull-Rom splines.

    Args:
        contour: Array-like of shape (N, 2), contour points as (x, y).
        num_control_points: Number of control points sampled from the contour.
        num_samples: Number of interpolated points to generate.
        return_control_points: If True, also return sampled control points.

    Returns:
        np.ndarray of shape (num_samples, 2) with interpolated points.
        If return_control_points=True, returns a tuple
        (interpolated_points, control_points).
    """
    pts = np.asarray(contour, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("contour must have shape (N, 2)")
    if pts.shape[0] < 4:
        raise ValueError("contour must contain at least 4 points")
    if num_control_points < 4:
        raise ValueError("num_control_points must be >= 4")
    if num_samples < 2:
        raise ValueError("num_samples must be >= 2")

    n = pts.shape[0]

    if num_control_points >= n:
        control = pts.copy()
    else:
        idx = np.linspace(0, n, num_control_points, endpoint=False)
        idx = np.clip(np.round(idx).astype(int), 0, n - 1)
        control = pts[idx]

    m = control.shape[0]
    segments = m

    def _catmull_rom(p0, p1, p2, p3, t):
        t2 = t * t
        t3 = t2 * t
        return 0.5 * (
            (2.0 * p1)
            + (-p0 + p2) * t
            + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
            + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
        )

    t_global = np.linspace(0, segments, num_samples, endpoint=False)
    seg_ids = np.floor(t_global).astype(int)
    seg_ids = np.clip(seg_ids, 0, segments - 1)
    t_local = t_global - seg_ids

    out = np.empty((num_samples, 2), dtype=np.float64)
    for i, (seg, t) in enumerate(zip(seg_ids, t_local)):
        i1 = seg
        i2 = (seg + 1) % m
        i0 = (i1 - 1) % m
        i3 = (i2 + 1) % m

        out[i] = _catmull_rom(control[i0], control[i1], control[i2], control[i3], t)

    if return_control_points:
        return out, control
    return out


def fit_spline_contours(
    contour_map: dict[int, list[np.ndarray]],
    num_control_points: int,
    num_samples: int = 400,
    return_nodes: bool = False,
):
    """Fit Catmull-Rom splines for contours in each frame."""
    if num_control_points < 4:
        raise ValueError("num_control_points must be >= 4")

    spline_map: dict[int, list[np.ndarray]] = {}
    node_map: dict[int, list[np.ndarray]] = {}
    for frame_idx, contours in contour_map.items():
        frame_out: list[np.ndarray] = []
        frame_nodes: list[np.ndarray] = []
        for contour in contours:
            pts = np.asarray(contour)
            if pts.ndim != 2 or pts.shape[1] != 2:
                continue
            if pts.shape[0] < 4:
                frame_out.append(pts)
                if return_nodes:
                    frame_nodes.append(pts)
                continue
            if return_nodes:
                smooth, control = interpolate_contour_catmull_rom(
                    pts,
                    num_control_points=num_control_points,
                    num_samples=num_samples,
                    return_control_points=True,
                )
                frame_nodes.append(control)
            else:
                smooth = interpolate_contour_catmull_rom(
                    pts,
                    num_control_points=num_control_points,
                    num_samples=num_samples,
                    return_control_points=False,
                )
            frame_out.append(smooth)
        spline_map[int(frame_idx)] = frame_out
        if return_nodes:
            node_map[int(frame_idx)] = frame_nodes

    if return_nodes:
        return spline_map, node_map
    return spline_map


def sample_outline_curve(outline) -> np.ndarray:
    """Sample a closed Catmull-Rom spline through custom mask outline vertices.

    Args:
        outline: Array-like of shape (N, 2), N >= 4, vertices as (x, y).

    Returns:
        np.ndarray of shape (num_samples, 2) with points on the closed curve.
    """
    pts = np.asarray(outline, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 4:
        raise ValueError("outline must have shape (N, 2) with N >= 4")
    num_samples = max(400, pts.shape[0] * 10)
    return interpolate_contour_catmull_rom(
        pts,
        num_control_points=pts.shape[0],
        num_samples=num_samples,
    )


def point_segment_distance_sq(point, seg_start, seg_end) -> float:
    """Squared distance from a point to a line segment."""
    p = np.asarray(point, dtype=np.float64)
    a = np.asarray(seg_start, dtype=np.float64)
    ab = np.asarray(seg_end, dtype=np.float64) - a
    denom = float(ab @ ab)
    t = 0.0 if denom == 0.0 else float(np.clip((p - a) @ ab / denom, 0.0, 1.0))
    d = a + t * ab - p
    return float(d @ d)


def build_custom_mask(outline, height: int, width: int) -> np.ndarray:
    """Rasterize a custom mask outline into a binary mask.

    Args:
        outline: Array-like of shape (N, 2), N >= 4, vertices as (x, y) = (col, row).
        height: Mask rows.
        width: Mask columns.

    Returns:
        uint8 mask of shape (height, width), 1 inside the closed spline.
    """
    curve = sample_outline_curve(outline)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(curve).astype(np.int32)], 1)
    return mask