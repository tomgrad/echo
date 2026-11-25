import json

from echo_viewer.descriptions import Descriptions, FILE_NAME
from echo_viewer.session import RecordingInfo, _error_info


def _info(path, uid="1.2.3"):
    base = _error_info(path, "x")
    return RecordingInfo(**{**base.__dict__, "sop_instance_uid": uid, "error": None})


def test_missing_file_is_empty(tmp_path):
    d = Descriptions.load(tmp_path)
    assert d.get(_info(tmp_path / "a.dcm")) == ""
    assert d.warning is None


def test_set_get_roundtrip(tmp_path):
    info = _info(tmp_path / "a.dcm")
    d = Descriptions.load(tmp_path)
    d.set(info, "PLAX")
    assert Descriptions.load(tmp_path).get(info) == "PLAX"
    assert json.loads((tmp_path / FILE_NAME).read_text()) == {"1.2.3": "PLAX"}


def test_empty_text_removes_entry(tmp_path):
    info = _info(tmp_path / "a.dcm")
    d = Descriptions.load(tmp_path)
    d.set(info, "A2C")
    d.set(info, "  ")
    assert d.get(info) == ""
    assert json.loads((tmp_path / FILE_NAME).read_text()) == {}


def test_text_stripped_to_one_line(tmp_path):
    info = _info(tmp_path / "a.dcm")
    d = Descriptions.load(tmp_path)
    d.set(info, "  sub\ncostal ")
    assert d.get(info) == "sub costal"


def test_falls_back_to_relative_path_without_uid(tmp_path):
    info = _info(tmp_path / "sub" / "a.dcm", uid="")
    d = Descriptions.load(tmp_path)
    d.set(info, "A4C")
    assert json.loads((tmp_path / FILE_NAME).read_text()) == {"sub/a.dcm": "A4C"}
    assert Descriptions.load(tmp_path).get(info) == "A4C"


def test_corrupt_file_warns_and_is_empty(tmp_path):
    (tmp_path / FILE_NAME).write_text("{nope")
    d = Descriptions.load(tmp_path)
    assert d.warning is not None
    assert d.get(_info(tmp_path / "a.dcm")) == ""
