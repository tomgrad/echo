import cv2
import numpy as np
import pytest

from echo_core import video_io
from echo_viewer.frames import decode_frame, decode_loop
from echo_viewer.session import scan_session


def _write_video(path, fourcc, frames=5, rows=32, cols=48, fps=20.0):
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*fourcc), fps, (cols, rows)
    )
    assert writer.isOpened()
    for i in range(frames):
        writer.write(np.full((rows, cols, 3), 40 * i, dtype=np.uint8))
    writer.release()


@pytest.mark.parametrize("name,fourcc", [("a.avi", "MJPG"), ("b.mp4", "mp4v")])
def test_scan_and_decode_video(tmp_path, write_dicom, name, fourcc):
    _write_video(tmp_path / name, fourcc)
    session = scan_session(tmp_path)
    (info,) = session.recordings
    assert info.error is None
    assert (info.frames, info.rows, info.cols) == (5, 32, 48)
    assert info.fps == pytest.approx(20.0)
    assert info.is_color and not info.is_still

    loop = decode_loop(info)
    assert loop.frames.shape == (5, 32, 48, 3)
    assert loop.levels is None
    assert decode_frame(info, 2).shape == (32, 48, 3)


def test_video_listed_with_dicom(tmp_path, write_dicom):
    write_dicom("x.dcm")
    _write_video(tmp_path / "v.avi", "MJPG")
    assert len(scan_session(tmp_path).recordings) == 2


def test_broken_video_is_error_entry(tmp_path):
    (tmp_path / "bad.mp4").write_bytes(b"not a video")
    (info,) = scan_session(tmp_path).recordings
    assert info.error


def test_is_video():
    assert video_io.is_video("a/B.AVI") and not video_io.is_video("a.dcm")
