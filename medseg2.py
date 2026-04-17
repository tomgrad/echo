from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Sequence, Tuple
import importlib

import numpy as np


def _load_npz_predictor_builder(label):
    """Load NPZ SAM2 predictor builder from installed sam2 package."""
    try:
        build_mod = importlib.import_module("sam2.build_sam")
        return getattr(build_mod, "build_sam2_video_predictor_npz")
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            f"Could not import build_sam2_video_predictor_npz for {label} from the installed sam2 package."
        ) from exc


def _resolve_runtime_dependencies(label):
    """Validate required runtime deps once and return initialized modules/builders."""
    try:
        import torch
    except Exception as exc:  # pragma: no cover - depends on runtime env
        raise RuntimeError(
            f"Could not import torch for {label}. Ensure PyTorch with CUDA is installed."
        ) from exc

    build_sam2_video_predictor_npz = _load_npz_predictor_builder(label)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required by the MedSeg2 workflow.")

    torch.set_float32_matmul_precision("high")
    return torch, build_sam2_video_predictor_npz


@dataclass
class PreparedVolume:
    vol_u8: np.ndarray
    img_t: Any
    height: int
    width: int


ProgressCallback = Callable[[int, int, str], None]


class MedSeg2Segmenter:
    """Common SAM2-family wrapper for keyframe-driven DICOM segmentation."""

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/MedSAM2/MedSAM2_latest.pt",
        model_cfg: str = "configs/sam2.1_hiera_t512.yaml",
        image_size: int = 512,
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.model_cfg = model_cfg
        self.image_size = image_size
        self.torch, self._build_sam2_video_predictor_npz = _resolve_runtime_dependencies(
            self.__class__.__name__
        )
        self._predictor = self._create_predictor()

    def _create_predictor(self):
        raise NotImplementedError("Subclasses must implement _create_predictor().")


class Sam2Segmenter(MedSeg2Segmenter):
    """SAM2 adapter using NPZ predictor for DICOM tensor workflows."""

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/SAM2/sam2.1_hiera_tiny.pt",
        model_cfg: str = "configs/sam2.1_hiera_t.yaml",
        image_size: int = 512,
    ) -> None:
        super().__init__(checkpoint_path=checkpoint_path, model_cfg=model_cfg, image_size=image_size)

    def _create_predictor(self):
        hydra_overrides_extra = [f"++model.image_size={int(self.image_size)}"]
        return self._build_sam2_video_predictor_npz(
            self.model_cfg,
            self.checkpoint_path,
            device="cuda",
            hydra_overrides_extra=hydra_overrides_extra,
        )

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
        v = self.torch.from_numpy(vol_u8).float().unsqueeze(1) / 255.0
        v = v.repeat(1, 3, 1, 1)
        v = self.torch.nn.functional.interpolate(
            v,
            size=(self.image_size, self.image_size),
            mode="bilinear",
            align_corners=False,
        )

        img_mean = self.torch.tensor((0.485, 0.456, 0.406), dtype=self.torch.float32)[None, :, None, None]
        img_std = self.torch.tensor((0.229, 0.224, 0.225), dtype=self.torch.float32)[None, :, None, None]

        img_t = v.cuda(non_blocking=True)
        img_t -= img_mean.cuda(non_blocking=True)
        img_t /= img_std.cuda(non_blocking=True)

        return PreparedVolume(vol_u8=vol_u8, img_t=img_t, height=height, width=width)

    @staticmethod
    def _prompt_from_points(points: Sequence[Sequence[int]]) -> Tuple[np.ndarray, np.ndarray]:
        if not points:
            raise ValueError("No prompt points available for this keyframe.")

        # UI/image-view coordinates are stored in display order (row, col).
        # SAM expects prompt coordinates in (x, y) = (col, row).
        coords = np.array([[p[1], p[0]] for p in points], dtype=np.float32)
        labels = np.array([1 if p[2] else 0 for p in points], dtype=np.int32)
        return coords, labels

    @staticmethod
    def _frame_from_logits(out_obj_ids, out_mask_logits) -> np.ndarray:
        if len(out_obj_ids) == 0:
            raise ValueError("No object ids returned for frame reconstruction.")

        first_mask = (out_mask_logits[0] > 0.0).detach().to("cpu").numpy()[0]
        merged = np.zeros_like(first_mask, dtype=np.uint16)
        for index, out_obj_id in enumerate(out_obj_ids):
            obj_mask = (out_mask_logits[index] > 0.0).detach().to("cpu").numpy()[0].astype(bool)
            out_obj_id = int(out_obj_id)
            take_obj = obj_mask & ((merged == 0) | (out_obj_id < merged))
            merged[take_obj] = out_obj_id
        return merged

    @staticmethod
    def _binary_mask_for_obj(label_volume: np.ndarray, obj_id: int) -> np.ndarray:
        return (np.asarray(label_volume) == int(obj_id)).astype(np.uint8)

    def _apply_prompts_on_frame(self, inference_state, frame_idx: int, obj_points: Dict[int, Sequence[Sequence[int]]]):
        frame_mask = None
        for obj_id, points in sorted(obj_points.items()):
            coords, labels = self._prompt_from_points(points)
            _, out_obj_ids, out_mask_logits = self._predictor.add_new_points_or_box(
                inference_state=inference_state,
                frame_idx=int(frame_idx),
                obj_id=int(obj_id),
                points=coords,
                labels=labels,
            )
            frame_mask = self._frame_from_logits(out_obj_ids, out_mask_logits)

        if frame_mask is None:
            raise ValueError(f"No prompts available to apply on frame {frame_idx}.")
        return frame_mask

    def _segment_multi_object_range(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        start_frame_points_by_obj: Dict[int, Sequence[Sequence[int]]],
        reverse: bool = False,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        if not start_frame_points_by_obj:
            raise ValueError("At least one object prompt set is required.")
        if reverse:
            if start_frame_idx < end_frame_idx:
                raise ValueError("For backward range, start_frame_idx must be >= end_frame_idx")
            total_frames = start_frame_idx - end_frame_idx + 1
            stage = "Propagating backward"
        else:
            if end_frame_idx < start_frame_idx:
                raise ValueError("end_frame_idx must be >= start_frame_idx")
            total_frames = end_frame_idx - start_frame_idx + 1
            stage = "Propagating forward"

        prep = self._prepare_volume(pixel_array, dicom_ds)
        segs_3d = np.zeros((prep.vol_u8.shape[0], prep.height, prep.width), dtype=np.uint16)
        prompt_items = sorted((int(obj_id), points) for obj_id, points in start_frame_points_by_obj.items() if points)
        if not prompt_items:
            raise ValueError("No prompt points available for multi-object propagation.")

        total = len(prompt_items) + total_frames
        processed = set()
        if progress_callback is not None:
            progress_callback(0, total, "Initializing")

        with self.torch.inference_mode(), self.torch.autocast("cuda", dtype=self.torch.bfloat16):
            inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
            prompt_count = 0
            for obj_id, points in prompt_items:
                segs_3d[start_frame_idx] = self._apply_prompts_on_frame(
                    inference_state,
                    start_frame_idx,
                    {obj_id: points},
                )
                prompt_count += 1
                if progress_callback is not None:
                    progress_callback(prompt_count, total, "Adding object prompts")

            processed.add(start_frame_idx)
            if progress_callback is not None:
                progress_callback(prompt_count + len(processed), total, stage)

            for out_frame_idx, out_obj_ids, out_mask_logits in self._predictor.propagate_in_video(
                inference_state,
                reverse=reverse,
            ):
                if reverse:
                    if out_frame_idx > start_frame_idx:
                        continue
                    if out_frame_idx < end_frame_idx:
                        break
                else:
                    if out_frame_idx < start_frame_idx:
                        continue
                    if out_frame_idx > end_frame_idx:
                        break

                segs_3d[out_frame_idx] = self._frame_from_logits(out_obj_ids, out_mask_logits)
                if out_frame_idx not in processed:
                    processed.add(out_frame_idx)
                    if progress_callback is not None:
                        progress_callback(prompt_count + len(processed), total, stage)

            self._predictor.reset_state(inference_state)

        return segs_3d

    def segment_single_keyframe(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        frame_idx: int,
        obj_id: int,
        frame_points: Sequence[Sequence[int]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        label_volume = self.segment_single_keyframe_multi_object(
            pixel_array=pixel_array,
            dicom_ds=dicom_ds,
            frame_idx=frame_idx,
            frame_points_by_obj={int(obj_id): frame_points},
            progress_callback=progress_callback,
        )
        return self._binary_mask_for_obj(label_volume, obj_id)

    def segment_single_keyframe_multi_object(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        frame_idx: int,
        frame_points_by_obj: Dict[int, Sequence[Sequence[int]]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        return self._segment_multi_object_range(
            pixel_array=pixel_array,
            dicom_ds=dicom_ds,
            start_frame_idx=frame_idx,
            end_frame_idx=frame_idx,
            start_frame_points_by_obj=frame_points_by_obj,
            reverse=False,
            progress_callback=progress_callback,
        )

    def segment_forward_range(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        obj_id: int,
        start_frame_points: Sequence[Sequence[int]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        label_volume = self.segment_forward_range_multi_object(
            pixel_array=pixel_array,
            dicom_ds=dicom_ds,
            start_frame_idx=start_frame_idx,
            end_frame_idx=end_frame_idx,
            start_frame_points_by_obj={int(obj_id): start_frame_points},
            progress_callback=progress_callback,
        )
        return self._binary_mask_for_obj(label_volume, obj_id)

    def segment_forward_range_multi_object(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        start_frame_points_by_obj: Dict[int, Sequence[Sequence[int]]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        return self._segment_multi_object_range(
            pixel_array=pixel_array,
            dicom_ds=dicom_ds,
            start_frame_idx=start_frame_idx,
            end_frame_idx=end_frame_idx,
            start_frame_points_by_obj=start_frame_points_by_obj,
            reverse=False,
            progress_callback=progress_callback,
        )

    def segment_backward_range(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        obj_id: int,
        start_frame_points: Sequence[Sequence[int]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        label_volume = self.segment_backward_range_multi_object(
            pixel_array=pixel_array,
            dicom_ds=dicom_ds,
            start_frame_idx=start_frame_idx,
            end_frame_idx=end_frame_idx,
            start_frame_points_by_obj={int(obj_id): start_frame_points},
            progress_callback=progress_callback,
        )
        return self._binary_mask_for_obj(label_volume, obj_id)

    def segment_backward_range_multi_object(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        start_frame_idx: int,
        end_frame_idx: int,
        start_frame_points_by_obj: Dict[int, Sequence[Sequence[int]]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        return self._segment_multi_object_range(
            pixel_array=pixel_array,
            dicom_ds=dicom_ds,
            start_frame_idx=start_frame_idx,
            end_frame_idx=end_frame_idx,
            start_frame_points_by_obj=start_frame_points_by_obj,
            reverse=True,
            progress_callback=progress_callback,
        )

    def segment_all_with_keyframes(
        self,
        pixel_array: np.ndarray,
        dicom_ds,
        key_frames: Sequence[int],
        key_frame_points: Dict[int, Dict[int, Sequence[Sequence[int]]]],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> np.ndarray:
        if not key_frames:
            raise ValueError("At least one keyframe is required.")
        if not key_frame_points:
            raise ValueError("At least one object prompt set is required.")

        prep = self._prepare_volume(pixel_array, dicom_ds)
        frame_count = prep.vol_u8.shape[0]
        segs_3d = np.zeros((frame_count, prep.height, prep.width), dtype=np.uint16)
        sorted_kf = sorted(set(int(k) for k in key_frames) & set(range(frame_count)))
        if not sorted_kf:
            raise ValueError("No keyframes are within frame range.")

        points_by_kf = {frame_idx: {} for frame_idx in sorted_kf}
        for obj_id, obj_frames in key_frame_points.items():
            for frame_idx, points in obj_frames.items():
                frame_idx = int(frame_idx)
                if frame_idx in points_by_kf and points:
                    points_by_kf[frame_idx][int(obj_id)] = points

        if not any(points_by_kf[frame_idx] for frame_idx in sorted_kf):
            raise ValueError("No prompt points available for multi-object propagation.")

        processed = set()
        if progress_callback is not None:
            progress_callback(0, frame_count, "Initializing")

        with self.torch.inference_mode(), self.torch.autocast("cuda", dtype=self.torch.bfloat16):
            # Forward propagation from each keyframe to the next keyframe boundary.
            for idx, frame_idx in enumerate(sorted_kf):
                obj_points = points_by_kf.get(frame_idx, {})
                if not obj_points:
                    continue

                next_kf = sorted_kf[idx + 1] if idx + 1 < len(sorted_kf) else frame_count - 1
                inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)

                segs_3d[frame_idx] = self._apply_prompts_on_frame(inference_state, frame_idx, obj_points)

                if frame_idx not in processed:
                    processed.add(frame_idx)
                    if progress_callback is not None:
                        progress_callback(len(processed), frame_count, "Propagating forward")

                for out_frame_idx, out_obj_ids, out_mask_logits in self._predictor.propagate_in_video(
                    inference_state
                ):
                    if out_frame_idx < frame_idx:
                        continue
                    if out_frame_idx > next_kf:
                        break
                    segs_3d[out_frame_idx] = self._frame_from_logits(out_obj_ids, out_mask_logits)
                    if out_frame_idx not in processed:
                        processed.add(out_frame_idx)
                        if progress_callback is not None:
                            progress_callback(len(processed), frame_count, "Propagating forward")

                self._predictor.reset_state(inference_state)

            first_kf = sorted_kf[0]
            first_obj_points = points_by_kf.get(first_kf, {})
            if first_kf > 0 and first_obj_points:
                inference_state = self._predictor.init_state(prep.img_t, prep.height, prep.width)
                segs_3d[first_kf] = self._apply_prompts_on_frame(inference_state, first_kf, first_obj_points)

                for out_frame_idx, out_obj_ids, out_mask_logits in self._predictor.propagate_in_video(
                    inference_state,
                    reverse=True,
                ):
                    if out_frame_idx > first_kf:
                        continue
                    if out_frame_idx < 0:
                        break
                    segs_3d[out_frame_idx] = self._frame_from_logits(out_obj_ids, out_mask_logits)
                    if out_frame_idx not in processed:
                        processed.add(out_frame_idx)
                    if progress_callback is not None:
                        progress_callback(len(processed), frame_count, "Propagating backward")

                self._predictor.reset_state(inference_state)

        return segs_3d


class MedSam2Segmenter(Sam2Segmenter):
    """MedSAM2 adapter with MedSAM2-specific defaults and NPZ predictor builder."""

    def __init__(
        self,
        checkpoint_path: str = "checkpoints/MedSAM2/MedSAM2_latest.pt",
        model_cfg: str = "configs/sam2.1_hiera_t512.yaml",
        image_size: int = 512,
    ) -> None:
        super().__init__(checkpoint_path=checkpoint_path, model_cfg=model_cfg, image_size=image_size)

    def _create_predictor(self):
        hydra_overrides_extra = [f"++model.image_size={int(self.image_size)}"]
        return self._build_sam2_video_predictor_npz(
            self.model_cfg,
            self.checkpoint_path,
            device="cuda",
            hydra_overrides_extra=hydra_overrides_extra,
        )
