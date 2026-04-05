from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence, Tuple
import importlib

import numpy as np


@dataclass
class PreparedVolume:
    vol_u8: np.ndarray
    img_t: Any
    height: int
    width: int


ProgressCallback = Callable[[int, int, str], None]


class MedSeg2Segmenter:
    """Thin MedSAM2 wrapper for keyframe-driven DICOM segmentation."""

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/MedSAM2_latest.pt",
        model_cfg: str = "configs/sam2.1_hiera_t512.yaml",
        image_size: int = 512,
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.model_cfg = model_cfg
        self.image_size = image_size
        self._predictor = None
        self._torch = None

    def _ensure_loaded(self):
        if self._predictor is not None:
            return

        try:
            import torch
            build_mod = importlib.import_module("sam2.build_sam")
            build_sam2_video_predictor_npz = getattr(build_mod, "build_sam2_video_predictor_npz")
        except Exception as exc:  # pragma: no cover - depends on runtime env
            raise RuntimeError(
                "Could not import MedSAM2 dependencies (torch/sam2)."
            ) from exc

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required by the MedSeg2 workflow.")

        torch.set_float32_matmul_precision("high")
        self._predictor = build_sam2_video_predictor_npz(self.model_cfg, self.checkpoint_path)
        self._torch = torch

    @staticmethod
    def _read_window_from_dicom(ds) -> Tuple[Optional[float], Optional[float]]:
        center = getattr(ds, "WindowCenter", None)
        width = getattr(ds, "WindowWidth", None)
        if isinstance(center, (list, tuple)):
            center = center[0]
        if isinstance(width, (list, tuple)):
            width = width[0]
        try:
            center = float(center) if center is not None else None
            width = float(width) if width is not None else None
        except Exception:
            center, width = None, None
        return center, width

    def _prepare_volume(self, pixel_array: np.ndarray, dicom_ds) -> PreparedVolume:
        self._ensure_loaded()
        assert self._torch is not None

        arr = pixel_array.astype(np.float32)
        if arr.ndim == 2:
            vol = arr[None, ...]
        elif arr.ndim == 3:
            vol = arr
        else:
            raise ValueError(f"Unsupported pixel_array shape: {arr.shape}")

        wc, ww = self._read_window_from_dicom(dicom_ds)
        if wc is not None and ww is not None and ww > 1e-6:
            lo = wc - ww / 2.0
            hi = wc + ww / 2.0
        else:
            lo, hi = np.percentile(vol, [0.5, 99.5])

        vol_clip = np.clip(vol, lo, hi)
        vol_u8 = (
            (vol_clip - vol_clip.min()) / max(vol_clip.max() - vol_clip.min(), 1e-6) * 255.0
        ).astype(np.uint8)

        height, width = vol_u8.shape[1:]

        # Convert (D,H,W) -> (D,3,S,S) with bilinear resize.
        v = self._torch.from_numpy(vol_u8).float().unsqueeze(1) / 255.0
        v = v.repeat(1, 3, 1, 1)
        v = self._torch.nn.functional.interpolate(
            v,
            size=(self.image_size, self.image_size),
            mode="bilinear",
            align_corners=False,
        )

        img_mean = self._torch.tensor((0.485, 0.456, 0.406), dtype=self._torch.float32)[None, :, None, None]
        img_std = self._torch.tensor((0.229, 0.224, 0.225), dtype=self._torch.float32)[None, :, None, None]

        img_t = v.cuda(non_blocking=True)
        img_t -= img_mean.cuda(non_blocking=True)
        img_t /= img_std.cuda(non_blocking=True)

        return PreparedVolume(vol_u8=vol_u8, img_t=img_t, height=height, width=width)

    @staticmethod
    def _prompt_from_points(points: Sequence[Sequence[int]]) -> Tuple[np.ndarray, np.ndarray]:
        if not points:
            raise ValueError("No prompt points available for this keyframe.")

        coords = np.array([[p[0], p[1]] for p in points], dtype=np.float32)
        labels = np.array([1 if p[2] else 0 for p in points], dtype=np.int32)
        return coords, labels

    @staticmethod
    def _mask_from_logits(mask_logits, torch_mod) -> np.ndarray:
        return (mask_logits[0] > 0.0).detach().to("cpu").numpy()[0].astype(np.uint8)

    def segment_single_keyframe(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        frame_idx: int,
        frame_points: Sequence[Sequence[int]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        self._ensure_loaded()
        assert self._torch is not None

        prep = self._prepare_volume(pixel_array, dicom_ds)
        segs_3d = np.zeros_like(prep.vol_u8, dtype=np.uint8)
        coords, labels = self._prompt_from_points(frame_points)
        total = 1
        if progress_callback is not None:
            progress_callback(0, total, "Initializing")

        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
            _, _, out_mask_logits = self._predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=frame_idx,
                obj_id=1,
                points=coords,
                labels=labels,
            )
            segs_3d[frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
            if progress_callback is not None:
                progress_callback(1, total, "Segmenting")
            self._predictor.reset_state(inference_state)

        return segs_3d

    def segment_forward_range(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        start_frame_points: Sequence[Sequence[int]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        self._ensure_loaded()
        assert self._torch is not None

        if end_frame_idx < start_frame_idx:
            raise ValueError("end_frame_idx must be >= start_frame_idx")

        prep = self._prepare_volume(pixel_array, dicom_ds)
        segs_3d = np.zeros_like(prep.vol_u8, dtype=np.uint8)
        coords, labels = self._prompt_from_points(start_frame_points)
        total = end_frame_idx - start_frame_idx + 1
        processed = set()
        if progress_callback is not None:
            progress_callback(0, total, "Initializing")

        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
            _, _, out_mask_logits = self._predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=start_frame_idx,
                obj_id=1,
                points=coords,
                labels=labels,
            )
            segs_3d[start_frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
            processed.add(start_frame_idx)
            if progress_callback is not None:
                progress_callback(len(processed), total, "Propagating forward")

            for out_frame_idx, _, out_mask_logits in self._predictor.propagate_in_video(inference_state):
                if out_frame_idx < start_frame_idx:
                    continue
                if out_frame_idx > end_frame_idx:
                    break
                segs_3d[out_frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
                if out_frame_idx not in processed:
                    processed.add(out_frame_idx)
                    if progress_callback is not None:
                        progress_callback(len(processed), total, "Propagating forward")

            self._predictor.reset_state(inference_state)

        return segs_3d

    def segment_backward_range(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        start_frame_points: Sequence[Sequence[int]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        self._ensure_loaded()
        assert self._torch is not None

        if start_frame_idx < end_frame_idx:
            raise ValueError("For backward range, start_frame_idx must be >= end_frame_idx")

        prep = self._prepare_volume(pixel_array, dicom_ds)
        segs_3d = np.zeros_like(prep.vol_u8, dtype=np.uint8)
        coords, labels = self._prompt_from_points(start_frame_points)
        total = start_frame_idx - end_frame_idx + 1
        processed = set()
        if progress_callback is not None:
            progress_callback(0, total, "Initializing")

        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
            _, _, out_mask_logits = self._predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=start_frame_idx,
                obj_id=1,
                points=coords,
                labels=labels,
            )
            segs_3d[start_frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
            processed.add(start_frame_idx)
            if progress_callback is not None:
                progress_callback(len(processed), total, "Propagating backward")

            for out_frame_idx, _, out_mask_logits in self._predictor.propagate_in_video(
                inference_state, reverse=True
            ):
                if out_frame_idx > start_frame_idx:
                    continue
                if out_frame_idx < end_frame_idx:
                    break
                segs_3d[out_frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
                if out_frame_idx not in processed:
                    processed.add(out_frame_idx)
                    if progress_callback is not None:
                        progress_callback(len(processed), total, "Propagating backward")

            self._predictor.reset_state(inference_state)

        return segs_3d

    def segment_all_with_keyframes(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        key_frames: Sequence[int],
        key_frame_points: Dict[int, Sequence[Sequence[int]]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        self._ensure_loaded()
        assert self._torch is not None

        if not key_frames:
            raise ValueError("At least one keyframe is required.")

        sorted_kf = sorted(set(int(k) for k in key_frames))
        prep = self._prepare_volume(pixel_array, dicom_ds)
        frame_count = prep.vol_u8.shape[0]
        segs_3d = np.zeros((frame_count, prep.height, prep.width), dtype=np.uint8)
        processed = set()
        if progress_callback is not None:
            progress_callback(0, frame_count, "Initializing")

        with self._torch.inference_mode(), self._torch.autocast("cuda", dtype=self._torch.bfloat16):
            # Forward segmentation between successive keyframes (and last keyframe to end).
            for idx, kf in enumerate(sorted_kf):
                if kf < 0 or kf >= frame_count:
                    continue
                points = key_frame_points.get(kf, [])
                if not points:
                    continue

                next_kf = sorted_kf[idx + 1] if idx + 1 < len(sorted_kf) else frame_count - 1
                coords, labels = self._prompt_from_points(points)

                inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
                _, _, out_mask_logits = self._predictor.add_new_points_or_box(
                    inference_state=inference_state,
                    frame_idx=kf,
                    obj_id=1,
                    points=coords,
                    labels=labels,
                )
                segs_3d[kf] = self._mask_from_logits(out_mask_logits, self._torch)
                if kf not in processed:
                    processed.add(kf)
                    if progress_callback is not None:
                        progress_callback(len(processed), frame_count, "Propagating between keyframes")

                for out_frame_idx, _, out_mask_logits in self._predictor.propagate_in_video(inference_state):
                    if out_frame_idx < kf:
                        continue
                    if out_frame_idx > next_kf:
                        break
                    segs_3d[out_frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
                    if out_frame_idx not in processed:
                        processed.add(out_frame_idx)
                        if progress_callback is not None:
                            progress_callback(len(processed), frame_count, "Propagating between keyframes")

                self._predictor.reset_state(inference_state)

            first_kf = sorted_kf[0]
            # If the first frame is not a keyframe, run reverse propagation from first keyframe.
            if first_kf > 0:
                points = key_frame_points.get(first_kf, [])
                if points:
                    coords, labels = self._prompt_from_points(points)
                    inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
                    _, _, out_mask_logits = self._predictor.add_new_points_or_box(
                        inference_state=inference_state,
                        frame_idx=first_kf,
                        obj_id=1,
                        points=coords,
                        labels=labels,
                    )
                    segs_3d[first_kf] = self._mask_from_logits(out_mask_logits, self._torch)
                    if first_kf not in processed:
                        processed.add(first_kf)
                        if progress_callback is not None:
                            progress_callback(len(processed), frame_count, "Propagating to first frame")
                    for out_frame_idx, _, out_mask_logits in self._predictor.propagate_in_video(
                        inference_state,
                        reverse=True,
                    ):
                        if out_frame_idx > first_kf:
                            continue
                        segs_3d[out_frame_idx] = self._mask_from_logits(out_mask_logits, self._torch)
                        if out_frame_idx not in processed:
                            processed.add(out_frame_idx)
                            if progress_callback is not None:
                                progress_callback(len(processed), frame_count, "Propagating to first frame")
                    self._predictor.reset_state(inference_state)

        return segs_3d
