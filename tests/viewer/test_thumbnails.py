import numpy as np
from PySide6.QtGui import QImage


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
