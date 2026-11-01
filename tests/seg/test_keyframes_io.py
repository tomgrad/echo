import pytest

from echo_seg.keyframes_io import read_keyframes, write_keyframes


def test_round_trip(tmp_path):
    path = tmp_path / "kf.xml"
    points = {1: {3: [[4, 5, True], [6, 7, False]]}}
    outlines = {2: {0: [[1, 1], [5, 1], [3, 4]]}}
    write_keyframes(path, [0, 3], points, outlines)
    assert read_keyframes(path, 10) == ([0, 3], points, outlines)


def test_frame_outside_loaded_image_is_rejected(tmp_path):
    path = tmp_path / "kf.xml"
    write_keyframes(path, [9], {}, {})
    with pytest.raises(ValueError, match="outside"):
        read_keyframes(path, 5)


def test_wrong_root_and_incomplete_point(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<other/>")
    with pytest.raises(ValueError):
        read_keyframes(bad)
    bad.write_text('<keyframes><keyframe index="0"><point x="1"/></keyframe></keyframes>')
    with pytest.raises(ValueError, match="must include"):
        read_keyframes(bad)
