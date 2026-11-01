import numpy as np
from PySide6.QtGui import QImage

from echo_viewer.thumbnails import qimage_from_frame, thumbnail_qimage


def test_color_qimage_geometry_and_format():
    frame = np.zeros((8, 10, 3), dtype=np.uint8)
    image = qimage_from_frame(frame, None)
    assert image.format() == QImage.Format_RGB888
    assert (image.width(), image.height()) == (10, 8)


def test_mono_qimage_maps_levels_to_full_range():
    frame = np.array([[0, 100]], dtype=np.uint16)
    image = qimage_from_frame(frame, (0.0, 100.0))
    assert image.format() == QImage.Format_Grayscale8
    assert image.pixelColor(0, 0).red() == 0
    assert image.pixelColor(1, 0).red() == 255


def test_qimage_respects_row_stride_for_unaligned_widths():
    # Width 5: 15 bytes per RGB row and 5 per gray row, neither a multiple of 4.
    color = np.zeros((2, 5, 3), dtype=np.uint8)
    color[1, 0] = (10, 20, 30)
    pixel = qimage_from_frame(color, None).pixelColor(0, 1)
    assert (pixel.red(), pixel.green(), pixel.blue()) == (10, 20, 30)

    mono = np.zeros((2, 5), dtype=np.uint16)
    mono[1, 0] = 100
    image = qimage_from_frame(mono, (0.0, 100.0))
    assert image.pixelColor(0, 1).red() == 255
    assert image.pixelColor(4, 0).red() == 0


def test_thumbnail_scales_to_requested_width():
    image = thumbnail_qimage(np.zeros((100, 200, 3), dtype=np.uint8), None, width=50)
    assert image.width() == 50
    assert image.height() == 25


def _provider_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_cancelled_generation_results_are_dropped(write_dicom, tmp_path):
    from echo_viewer.session import scan_session
    from echo_viewer.thumbnails import ThumbnailProvider

    app = _provider_app()
    write_dicom("rec.dcm")
    info = scan_session(tmp_path).recordings[0]
    provider = ThumbnailProvider()
    got = []
    provider.thumbnail_ready.connect(lambda path, image: got.append(path))

    # A result queued under the old generation must not reach thumbnail_ready.
    stale = provider._generation
    provider.cancel_all()
    provider._raw_ready.emit(info.path, QImage(4, 4, QImage.Format_RGB888), stale)
    app.processEvents()
    assert got == []

    # The current generation still delivers.
    provider._raw_ready.emit(
        info.path, QImage(4, 4, QImage.Format_RGB888), provider._generation
    )
    app.processEvents()
    assert got == [info.path]
    provider.shutdown()


def test_request_after_shutdown_is_noop(write_dicom, tmp_path):
    from echo_viewer.session import scan_session
    from echo_viewer.thumbnails import ThumbnailProvider

    app = _provider_app()
    write_dicom("rec.dcm")
    info = scan_session(tmp_path).recordings[0]
    provider = ThumbnailProvider()
    got = []
    provider.thumbnail_ready.connect(lambda path, image: got.append(path))
    provider.thumbnail_failed.connect(lambda path, msg: got.append(path))
    provider.shutdown()
    provider.request(info)
    provider._pool.waitForDone()
    app.processEvents()
    assert got == []
