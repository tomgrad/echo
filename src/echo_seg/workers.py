import traceback

from PySide6.QtCore import QThread, Signal


def format_segmentation_error(exc, traceback_text=""):
    base_message = str(exc).strip() or f"{exc.__class__.__name__} (no message)"
    details = traceback_text.strip()
    if not details:
        return base_message
    # Keep dialog readable and bounded for large backend traces.
    return f"{base_message}\n\nDetails:\n{details[-4000:]}"


class SegmentationWorker(QThread):
    """Runs one segmentation call off the GUI thread and reports back through signals."""

    progress = Signal(int, int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, work_fn, parent=None):
        super().__init__(parent)
        self._work_fn = work_fn

    def run(self):
        try:
            result = self._work_fn(self.progress.emit)
        except Exception as exc:
            self.failed.emit(format_segmentation_error(exc, traceback.format_exc()))
            return
        self.succeeded.emit(result)
