from pathlib import Path

import numpy as np
import pytest

import dicom_io
from viewer.frames import FrameCache, Loop, decode_frame, decode_loop
from viewer.session import scan_session


def _info(write_dicom, **kwargs):
    path, arr = write_dicom("rec.dcm", **kwargs)
    return scan_session(path.parent).recordings[0], arr


def test_decode_color_loop(write_dicom):
    info, arr = _info(write_dicom, frames=3, color=True)
    loop = decode_loop(info)
    assert loop.frames.shape == (3, 8, 10, 3)
    assert loop.levels is None
    assert np.array_equal(loop.frames, arr)


def test_decode_monochrome_loop_has_levels(write_dicom):
    info, arr = _info(write_dicom, frames=3, color=False)
    loop = decode_loop(info)
    assert loop.frames.shape == (3, 8, 10)
    low, high = loop.levels
    assert low < high


def test_decode_single_frame(write_dicom):
    info, arr = _info(write_dicom, frames=4, color=True)
    assert np.array_equal(decode_frame(info, 2), arr[2])


def test_decode_still_loop_has_frame_axis(write_dicom):
    info, arr = _info(write_dicom, frames=1, color=True)
    loop = decode_loop(info)
    assert loop.frames.shape == (1, 8, 10, 3)


def test_decode_monochrome_still_has_frame_axis_and_levels(write_dicom):
    info, arr = _info(write_dicom, frames=1, color=False)
    loop = decode_loop(info)
    assert loop.frames.shape == (1, 8, 10)
    assert np.array_equal(decode_frame(info, 0), arr[0])
    low, high = loop.levels
    assert low < high


def test_cache_evicts_least_recently_used():
    cache = FrameCache(budget_bytes=120)
    a = Loop(np.zeros(50, dtype=np.uint8), None)
    b = Loop(np.zeros(50, dtype=np.uint8), None)
    c = Loop(np.zeros(50, dtype=np.uint8), None)
    cache.put(Path("a"), a)
    cache.put(Path("b"), b)
    assert cache.get(Path("a")) is a
    cache.put(Path("c"), c)
    assert cache.get(Path("b")) is None
    assert cache.get(Path("a")) is a
    assert cache.bytes_used == 100


def test_cache_replaces_same_path():
    cache = FrameCache(budget_bytes=1000)
    first = Loop(np.zeros(10, dtype=np.uint8), None)
    second = Loop(np.zeros(20, dtype=np.uint8), None)
    cache.put(Path("a"), first)
    cache.put(Path("a"), second)
    assert cache.get(Path("a")) is second
    assert cache.bytes_used == 20
    assert len(cache) == 1


def test_decode_loop_matches_stacked_frames_color(write_dicom):
    info, arr = _info(write_dicom, frames=5, color=True)
    loop = decode_loop(info)
    stacked = np.stack([decode_frame(info, i) for i in range(5)])
    assert loop.frames.dtype == stacked.dtype
    assert np.array_equal(loop.frames, stacked)
    assert np.array_equal(loop.frames, arr)


def test_decode_loop_matches_stacked_frames_monochrome(write_dicom):
    info, arr = _info(write_dicom, frames=5, color=False)
    loop = decode_loop(info)
    stacked = np.stack([decode_frame(info, i) for i in range(5)])
    assert loop.frames.dtype == stacked.dtype
    assert np.array_equal(loop.frames, stacked)
    assert np.array_equal(loop.frames, arr)
    assert loop.levels == dicom_io.mono_levels(stacked)
