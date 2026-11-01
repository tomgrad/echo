# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'viewer_window.ui'
##
## Created by: Qt User Interface Compiler version 6.12.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QListView,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QSizePolicy, QSpacerItem, QStatusBar, QVBoxLayout,
    QWidget)

class Ui_ViewerWindow(object):
    def setupUi(self, ViewerWindow):
        if not ViewerWindow.objectName():
            ViewerWindow.setObjectName(u"ViewerWindow")
        ViewerWindow.resize(1280, 800)
        self.centralwidget = QWidget(ViewerWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.toolbarFrame = QFrame(self.centralwidget)
        self.toolbarFrame.setObjectName(u"toolbarFrame")
        self.toolbarLayout = QHBoxLayout(self.toolbarFrame)
        self.toolbarLayout.setObjectName(u"toolbarLayout")
        self.openSessionButton = QPushButton(self.toolbarFrame)
        self.openSessionButton.setObjectName(u"openSessionButton")

        self.toolbarLayout.addWidget(self.openSessionButton)

        self.thumbnailsButton = QPushButton(self.toolbarFrame)
        self.thumbnailsButton.setObjectName(u"thumbnailsButton")
        self.thumbnailsButton.setCheckable(True)
        self.thumbnailsButton.setChecked(True)

        self.toolbarLayout.addWidget(self.thumbnailsButton)

        self.layoutCombo = QComboBox(self.toolbarFrame)
        self.layoutCombo.addItem("")
        self.layoutCombo.addItem("")
        self.layoutCombo.setObjectName(u"layoutCombo")

        self.toolbarLayout.addWidget(self.layoutCombo)

        self.playButton = QPushButton(self.toolbarFrame)
        self.playButton.setObjectName(u"playButton")

        self.toolbarLayout.addWidget(self.playButton)

        self.stopButton = QPushButton(self.toolbarFrame)
        self.stopButton.setObjectName(u"stopButton")

        self.toolbarLayout.addWidget(self.stopButton)

        self.syncCheckBox = QCheckBox(self.toolbarFrame)
        self.syncCheckBox.setObjectName(u"syncCheckBox")
        self.syncCheckBox.setChecked(True)

        self.toolbarLayout.addWidget(self.syncCheckBox)

        self.loopCheckBox = QCheckBox(self.toolbarFrame)
        self.loopCheckBox.setObjectName(u"loopCheckBox")
        self.loopCheckBox.setChecked(True)

        self.toolbarLayout.addWidget(self.loopCheckBox)

        self.toolbarSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.toolbarLayout.addItem(self.toolbarSpacer)


        self.verticalLayout.addWidget(self.toolbarFrame)

        self.bodyWidget = QWidget(self.centralwidget)
        self.bodyWidget.setObjectName(u"bodyWidget")
        self.bodyLayout = QHBoxLayout(self.bodyWidget)
        self.bodyLayout.setObjectName(u"bodyLayout")
        self.leftPanel = QFrame(self.bodyWidget)
        self.leftPanel.setObjectName(u"leftPanel")
        self.leftPanel.setMinimumSize(QSize(220, 0))
        self.leftPanel.setMaximumSize(QSize(260, 16777215))
        self.leftPanelLayout = QVBoxLayout(self.leftPanel)
        self.leftPanelLayout.setObjectName(u"leftPanelLayout")
        self.sessionLabel = QLabel(self.leftPanel)
        self.sessionLabel.setObjectName(u"sessionLabel")

        self.leftPanelLayout.addWidget(self.sessionLabel)

        self.thumbnailList = QListWidget(self.leftPanel)
        self.thumbnailList.setObjectName(u"thumbnailList")
        self.thumbnailList.setViewMode(QListView.ViewMode.IconMode)
        self.thumbnailList.setResizeMode(QListView.ResizeMode.Adjust)
        self.thumbnailList.setIconSize(QSize(180, 120))
        self.thumbnailList.setGridSize(QSize(200, 170))
        self.thumbnailList.setWordWrap(True)
        self.thumbnailList.setUniformItemSizes(True)

        self.leftPanelLayout.addWidget(self.thumbnailList)


        self.bodyLayout.addWidget(self.leftPanel)

        self.gridContainer = QWidget(self.bodyWidget)
        self.gridContainer.setObjectName(u"gridContainer")
        self.gridLayout = QGridLayout(self.gridContainer)
        self.gridLayout.setSpacing(4)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(4, 4, 4, 4)

        self.bodyLayout.addWidget(self.gridContainer)


        self.verticalLayout.addWidget(self.bodyWidget)

        ViewerWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(ViewerWindow)
        self.statusbar.setObjectName(u"statusbar")
        ViewerWindow.setStatusBar(self.statusbar)

        self.retranslateUi(ViewerWindow)

        self.layoutCombo.setCurrentIndex(1)


        QMetaObject.connectSlotsByName(ViewerWindow)
    # setupUi

    def retranslateUi(self, ViewerWindow):
        ViewerWindow.setWindowTitle(QCoreApplication.translate("ViewerWindow", u"Echo Viewer", None))
        self.openSessionButton.setText(QCoreApplication.translate("ViewerWindow", u"Open session", None))
        self.thumbnailsButton.setText(QCoreApplication.translate("ViewerWindow", u"Thumbnails", None))
        self.layoutCombo.setItemText(0, QCoreApplication.translate("ViewerWindow", u"1\u00d71", None))
        self.layoutCombo.setItemText(1, QCoreApplication.translate("ViewerWindow", u"2\u00d72", None))

        self.playButton.setText(QCoreApplication.translate("ViewerWindow", u"Play", None))
        self.stopButton.setText(QCoreApplication.translate("ViewerWindow", u"Stop", None))
        self.syncCheckBox.setText(QCoreApplication.translate("ViewerWindow", u"Sync", None))
        self.loopCheckBox.setText(QCoreApplication.translate("ViewerWindow", u"Loop", None))
        self.sessionLabel.setText(QCoreApplication.translate("ViewerWindow", u"No session", None))
    # retranslateUi

