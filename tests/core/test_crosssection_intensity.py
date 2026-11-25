import numpy as np
import pytest

pytest.importorskip("pyqtgraph")
from PySide6.QtWidgets import QApplication

from echo_core.widgets.crosssectionview import CrossSectionView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_intensity_curve_maps_high_to_top(app):
    view = CrossSectionView()
    view.set_cross_section(np.zeros((20, 5)))
    view.set_intensity(np.array([0.0, 1.0, np.nan, 0.5, 0.25]))
    view.set_intensity_visible(True)
    x, y = view._intensity_curve.getData()
    assert y[0] == 20.0 and y[1] == 0.0 and np.isnan(y[2]) and y[3] == 10.0
    view.set_intensity_visible(False)
    assert not view._intensity_curve.isVisible()
    view.set_intensity(None)
    assert view._intensity_curve.getData()[0] is None


def test_area_curve_independent(app):
    view = CrossSectionView()
    view.set_cross_section(np.zeros((20, 4)))
    view.set_area(np.array([0.0, 1.0, 0.5, 0.0]))
    view.set_area_visible(True)
    assert view._area_curve.getData()[1][1] == 0.0
    assert view._intensity_curve.getData()[0] is None
    view.set_area_visible(False)
    assert not view._area_curve.isVisible()
