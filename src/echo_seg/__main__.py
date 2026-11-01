import sys

from PySide6.QtWidgets import QApplication

from echo_seg.main_window import MainWindow
from echo_seg.segmenter import configure_torch_for_inference


def main() -> int:
    configure_torch_for_inference()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
