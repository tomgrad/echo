import pytest

from echo_viewer.session import recording_label, scan_session


def test_scan_orders_by_instance_and_reads_metadata(write_dicom, tmp_path):
    write_dicom("b.dcm", instance=2, dt="20260101120100.000")
    write_dicom("a.dcm", instance=1, dt="20260101120000.000")
    session = scan_session(tmp_path)
    assert [r.instance_number for r in session.recordings] == [1, 2]
    first = session.recordings[0]
    assert first.frames == 3
    assert first.fps == 25.0
    assert first.rows == 8 and first.cols == 10
    assert first.duration_s == pytest.approx(0.12)
    assert first.heart_rate == 60


def test_scan_is_recursive_and_skips_non_dicom(write_dicom, tmp_path):
    write_dicom("nested/rec.dcm", instance=1)
    (tmp_path / "notes.txt").write_text("not a study")
    session = scan_session(tmp_path)
    assert len(session.recordings) == 1
    assert session.recordings[0].path == (tmp_path / "nested/rec.dcm").resolve()


def test_corrupt_dcm_is_reported_not_skipped(tmp_path):
    (tmp_path / "bad.dcm").write_text("not a dicom")
    session = scan_session(tmp_path)
    assert len(session.recordings) == 1
    assert session.recordings[0].error
    assert recording_label(session.recordings[0], 1) == "REC 01 · error"


def test_empty_folder_returns_empty_session(tmp_path):
    session = scan_session(tmp_path)
    assert session.recordings == ()
    assert session.study_label == tmp_path.name


def test_study_label_prefers_description(write_dicom, tmp_path):
    write_dicom("rec.dcm", study_description="TTE Study")
    assert scan_session(tmp_path).study_label == "TTE Study"


def test_recording_label_format(write_dicom, tmp_path):
    write_dicom("rec.dcm", dt="20260101120000.000")
    info = scan_session(tmp_path).recordings[0]
    assert recording_label(info, 1) == (
        "REC 01 · inst 1 · 3f · 25 fps · 0.12s · 12:00:00"
    )


def test_still_label(write_dicom, tmp_path):
    write_dicom("still.dcm", frames=1, instance=2)
    info = scan_session(tmp_path).recordings[0]
    assert recording_label(info, 1) == (
        "REC 01 · inst 2 · 1f · 25 fps · 0.04s · 12:00:00 · STILL"
    )


def _patch_instance_number(path):
    data = path.read_bytes()
    marker = b"\x20\x00\x13\x00IS\x02\x00"
    idx = data.index(marker) + len(marker)
    path.write_bytes(data[:idx] + b"ab" + data[idx + 2:])


def test_empty_heart_rate_scans_with_none(write_dicom, tmp_path):
    write_dicom("rec.dcm", heart_rate="")
    session = scan_session(tmp_path)
    assert len(session.recordings) == 1
    info = session.recordings[0]
    assert info.error is None
    assert info.heart_rate is None


def test_non_numeric_instance_number_is_error_and_scan_continues(
    write_dicom, tmp_path
):
    write_dicom("a_good.dcm", instance=1)
    bad_path, _ = write_dicom("b_bad.dcm", instance=2)
    _patch_instance_number(bad_path)
    session = scan_session(tmp_path)
    assert len(session.recordings) == 2
    by_name = {r.path.name: r for r in session.recordings}
    assert by_name["a_good.dcm"].error is None
    bad = by_name["b_bad.dcm"]
    assert bad.error
    assert recording_label(bad, 1) == "REC 01 · error"


def test_uppercase_dcm_corrupt_file_is_reported(tmp_path):
    (tmp_path / "BAD.DCM").write_text("not a dicom")
    session = scan_session(tmp_path)
    assert len(session.recordings) == 1
    assert session.recordings[0].error
    assert recording_label(session.recordings[0], 1) == "REC 01 · error"
