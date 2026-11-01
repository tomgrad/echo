import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    UltrasoundMultiFrameImageStorage,
    generate_uid,
)


@pytest.fixture
def write_dicom(tmp_path):
    def _write(
        name="rec.dcm",
        *,
        frames=3,
        rows=8,
        cols=10,
        color=False,
        fps=25.0,
        frame_time=None,
        instance=1,
        dt="20260101120000.000",
        study_uid=None,
        series_uid=None,
        study_description="",
        series_description="",
        heart_rate=60,
        **extra,
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.MediaStorageSOPClassUID = UltrasoundMultiFrameImageStorage
        ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = UltrasoundMultiFrameImageStorage
        ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
        ds.Modality = "US"
        ds.PatientName = "Test^Patient"
        ds.PatientID = "1"
        ds.StudyInstanceUID = study_uid or generate_uid()
        ds.SeriesInstanceUID = series_uid or generate_uid()
        ds.StudyDate = "20260101"
        ds.StudyDescription = study_description
        ds.SeriesDescription = series_description
        ds.AcquisitionDateTime = dt
        ds.InstanceNumber = instance
        ds.HeartRate = heart_rate
        ds.Rows = rows
        ds.Columns = cols
        ds.NumberOfFrames = frames
        if fps is not None:
            ds.CineRate = str(int(fps))
        if frame_time is not None:
            ds.FrameTime = frame_time
        if color:
            ds.SamplesPerPixel = 3
            ds.PhotometricInterpretation = "RGB"
            ds.PlanarConfiguration = 0
            arr = np.zeros((frames, rows, cols, 3), dtype=np.uint8)
            arr[..., 1] = 128
        else:
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            arr = np.arange(frames * rows * cols, dtype=np.uint16).reshape(
                frames, rows, cols
            )
        ds.BitsAllocated = 8 if color else 16
        ds.BitsStored = 8 if color else 12
        ds.HighBit = 7 if color else 11
        ds.PixelRepresentation = 0
        ds.PixelData = arr.tobytes()
        for key, value in extra.items():
            setattr(ds, key, value)
        ds.save_as(path, enforce_file_format=True)
        return path, arr

    return _write
