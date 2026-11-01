import numpy as np
import pytest
from pydicom.dataelem import DataElement
from pydicom.datadict import tag_for_keyword
from pydicom.dataset import Dataset

from echo_core import dicom_io


def test_metadata_fallbacks():
    ds = Dataset()
    assert dicom_io.frame_count(ds) == 1
    assert dicom_io.is_still(ds)
    assert not dicom_io.is_color(ds)
    assert dicom_io.fps(ds) == 30.0

    ds.CineRate = "0"
    assert dicom_io.fps(ds) == 30.0

    ds.RecommendedDisplayFrameRate = 20
    assert dicom_io.fps(ds) == 20.0

    del ds.RecommendedDisplayFrameRate
    ds.FrameTime = 40.0
    assert dicom_io.fps(ds) == 25.0

    ds.SamplesPerPixel = 3
    assert dicom_io.is_color(ds)


def test_pixel_frames_and_single_frame(write_dicom):
    path, arr = write_dicom("rgb.dcm", frames=3, color=True)
    ds = dicom_io.read_dataset(path)
    frames = dicom_io.pixel_frames(ds)
    assert frames.shape == (3, 8, 10, 3)
    assert np.array_equal(dicom_io.pixel_frame(ds, 1), arr[1])


def test_monochrome_pixel_frames(write_dicom):
    path, arr = write_dicom("mono.dcm", frames=2, color=False)
    ds = dicom_io.read_dataset(path)
    frames = dicom_io.pixel_frames(ds)
    assert frames.shape == (2, 8, 10)
    assert np.array_equal(dicom_io.pixel_frame(ds, 0), arr[0])


def test_frame_count_tolerates_bad_values():
    ds = Dataset()
    # pydicom 3 rejects "abc" as an IS value on assignment, so store it as raw LO text.
    ds["NumberOfFrames"] = DataElement(0x00280008, "LO", "abc")
    assert dicom_io.frame_count(ds) == 1
    ds.NumberOfFrames = "0"
    assert dicom_io.frame_count(ds) == 1
    ds.NumberOfFrames = "7"
    assert dicom_io.frame_count(ds) == 7


def _raw(ds, keyword, value):
    # pydicom validates IS/DS assignments and rejects inf/nan; real files can
    # still carry such strings, so store them with a permissive VR.
    ds.add(DataElement(tag_for_keyword(keyword), "LO", value))


@pytest.mark.parametrize("cine", ["inf", "-inf", "nan", "0", "-5"])
def test_fps_ignores_non_finite_or_non_positive_cine_rate(cine):
    ds = Dataset()
    _raw(ds, "CineRate", cine)
    ds.FrameTime = 40.0
    assert dicom_io.fps(ds) == 25.0


def test_fps_falls_back_to_default_for_inf_and_nan_sources():
    ds = Dataset()
    _raw(ds, "CineRate", "inf")
    _raw(ds, "RecommendedDisplayFrameRate", "nan")
    assert dicom_io.fps(ds) == dicom_io.DEFAULT_FPS


def test_fps_ignores_frame_time_whose_rate_overflows():
    ds = Dataset()
    ds.FrameTime = 5e-324  # 1000 / FrameTime overflows to inf
    assert dicom_io.fps(ds) == dicom_io.DEFAULT_FPS
    ds.FrameTime = float("inf")
    assert dicom_io.fps(ds) == dicom_io.DEFAULT_FPS
