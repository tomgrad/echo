import sys

from PySide6.QtWidgets import QApplication

from echo_viewer.window import ViewerWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = ViewerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
