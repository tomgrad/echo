from PySide6.QtWidgets import QMainWindow

from viewer.ui_viewer_window import Ui_ViewerWindow


class ViewerWindow(QMainWindow, Ui_ViewerWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
