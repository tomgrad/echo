from dataclasses import dataclass
from pathlib import Path

import dicom_io


@dataclass(frozen=True)
class RecordingInfo:
    path: Path
    instance_number: int
    sop_instance_uid: str
    frames: int
    rows: int
    cols: int
    fps: float
    is_color: bool
    is_still: bool
    study_uid: str
    series_uid: str
    study_description: str
    series_description: str
    patient_name: str
    patient_id: str
    study_date: str
    acquisition_datetime: str
    heart_rate: int | None
    error: str | None = None

    @property
    def duration_s(self) -> float:
        if self.fps <= 0:
            return 0.0
        return self.frames / self.fps


@dataclass(frozen=True)
class Session:
    folder: Path
    study_label: str
    recordings: tuple[RecordingInfo, ...]


def _error_info(path: Path, message: str) -> RecordingInfo:
    return RecordingInfo(
        path=path,
        instance_number=0,
        sop_instance_uid="",
        frames=0,
        rows=0,
        cols=0,
        fps=0.0,
        is_color=False,
        is_still=False,
        study_uid="",
        series_uid="",
        study_description="",
        series_description="",
        patient_name="",
        patient_id="",
        study_date="",
        acquisition_datetime="",
        heart_rate=None,
        error=message,
    )


def _info_from_header(path: Path, ds) -> RecordingInfo:
    heart_rate = int(ds.HeartRate) if "HeartRate" in ds else None
    return RecordingInfo(
        path=path,
        instance_number=int(ds.get("InstanceNumber", 0) or 0),
        sop_instance_uid=str(ds.get("SOPInstanceUID", "")),
        frames=dicom_io.frame_count(ds),
        rows=int(ds.get("Rows", 0) or 0),
        cols=int(ds.get("Columns", 0) or 0),
        fps=dicom_io.fps(ds),
        is_color=dicom_io.is_color(ds),
        is_still=dicom_io.is_still(ds),
        study_uid=str(ds.get("StudyInstanceUID", "")),
        series_uid=str(ds.get("SeriesInstanceUID", "")),
        study_description=str(ds.get("StudyDescription", "")),
        series_description=str(ds.get("SeriesDescription", "")),
        patient_name=str(ds.get("PatientName", "")),
        patient_id=str(ds.get("PatientID", "")),
        study_date=str(ds.get("StudyDate", "")),
        acquisition_datetime=str(ds.get("AcquisitionDateTime", "")),
        heart_rate=heart_rate,
    )


def scan_session(folder: str | Path) -> Session:
    root = Path(folder).resolve()
    recordings: list[RecordingInfo] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        path = path.resolve()
        try:
            ds = dicom_io.read_header(path)
        except Exception as exc:
            if path.suffix.lower() != ".dcm":
                continue
            recordings.append(_error_info(path, str(exc) or type(exc).__name__))
            continue
        recordings.append(_info_from_header(path, ds))

    recordings.sort(
        key=lambda r: (r.instance_number, r.acquisition_datetime, r.path.name)
    )

    study_label = root.name
    for info in recordings:
        if info.error is None and info.study_description:
            study_label = info.study_description
            break

    return Session(folder=root, study_label=study_label, recordings=tuple(recordings))


def recording_label(info: RecordingInfo, index: int) -> str:
    if info.error is not None:
        return f"REC {index:02d} · error"
    clock = info.acquisition_datetime[8:14]
    if len(info.acquisition_datetime) < 14:
        clock_text = "--:--:--"
    else:
        clock_text = f"{clock[0:2]}:{clock[2:4]}:{clock[4:6]}"
    label = (
        f"REC {index:02d} · inst {info.instance_number} · {info.frames}f · "
        f"{info.fps:g} fps · {info.duration_s:.2f}s · {clock_text}"
    )
    if info.is_still:
        label += " · STILL"
    return label
