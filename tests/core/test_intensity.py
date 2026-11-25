import numpy as np
import pytest

from echo_core.intensity import masked_area, masked_mean_intensity, normalize_minmax


def test_mean_over_mask_any_label():
    vol = np.zeros((3, 4, 4))
    vol[0] = 10
    vol[1, :2] = 20
    vol[1, 2:] = 100
    mask = np.zeros((3, 4, 4), dtype=np.uint16)
    mask[0, 1:3, 1:3] = 1
    mask[1, :2] = 2
    out = masked_mean_intensity(vol, mask)
    assert out[0] == 10 and out[1] == 20 and np.isnan(out[2])


def test_shape_mismatch():
    with pytest.raises(ValueError):
        masked_mean_intensity(np.zeros((2, 3, 3)), np.zeros((2, 3, 4)))


def test_normalize():
    out = normalize_minmax(np.array([2.0, np.nan, 4.0, 3.0]))
    assert out[0] == 0 and out[2] == 1 and out[3] == 0.5 and np.isnan(out[1])
    assert normalize_minmax(np.array([5.0, 5.0])).tolist() == [0.5, 0.5]
    assert np.isnan(normalize_minmax(np.array([np.nan]))).all()


def test_masked_area():
    mask = np.zeros((3, 4, 4), dtype=np.uint16)
    mask[0, :2, :2] = 1
    mask[1, :1, :4] = 3
    assert masked_area(mask).tolist() == [4.0, 4.0, 0.0]
    with pytest.raises(ValueError):
        masked_area(np.zeros((4, 4)))
