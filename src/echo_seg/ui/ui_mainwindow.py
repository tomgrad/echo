# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QListView, QMainWindow, QMenuBar,
    QPushButton, QSizePolicy, QSpacerItem, QSpinBox,
    QSplitter, QStatusBar, QVBoxLayout, QWidget)

from echo_core.widgets.crosssectionview import CrossSectionView
from echo_core.widgets.imageview import ImageView

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1112, 963)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.horizontalLayout = QHBoxLayout(self.centralwidget)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.splitter = QSplitter(self.centralwidget)
        self.splitter.setObjectName(u"splitter")
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.imageView = ImageView(self.splitter)
        self.imageView.setObjectName(u"imageView")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(4)
        sizePolicy.setHeightForWidth(self.imageView.sizePolicy().hasHeightForWidth())
        self.imageView.setSizePolicy(sizePolicy)
        self.splitter.addWidget(self.imageView)
        self.crossSectionView = CrossSectionView(self.splitter)
        self.crossSectionView.setObjectName(u"crossSectionView")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(1)
        sizePolicy1.setHeightForWidth(self.crossSectionView.sizePolicy().hasHeightForWidth())
        self.crossSectionView.setSizePolicy(sizePolicy1)
        self.splitter.addWidget(self.crossSectionView)

        self.horizontalLayout.addWidget(self.splitter)

        self.frame = QFrame(self.centralwidget)
        self.frame.setObjectName(u"frame")
        self.frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.frame.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout = QVBoxLayout(self.frame)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.groupBox = QGroupBox(self.frame)
        self.groupBox.setObjectName(u"groupBox")
        self.gridLayout = QGridLayout(self.groupBox)
        self.gridLayout.setObjectName(u"gridLayout")
        self.openDicomButton = QPushButton(self.groupBox)
        self.openDicomButton.setObjectName(u"openDicomButton")

        self.gridLayout.addWidget(self.openDicomButton, 0, 0, 1, 1)

        self.loadKeyFramesButton = QPushButton(self.groupBox)
        self.loadKeyFramesButton.setObjectName(u"loadKeyFramesButton")

        self.gridLayout.addWidget(self.loadKeyFramesButton, 0, 1, 1, 1)

        self.checkpointsComboBox = QComboBox(self.groupBox)
        self.checkpointsComboBox.setObjectName(u"checkpointsComboBox")

        self.gridLayout.addWidget(self.checkpointsComboBox, 1, 0, 1, 3)

        self.saveKeyFramesButton = QPushButton(self.groupBox)
        self.saveKeyFramesButton.setObjectName(u"saveKeyFramesButton")

        self.gridLayout.addWidget(self.saveKeyFramesButton, 0, 2, 1, 1)

        self.exportMasksButton = QPushButton(self.groupBox)
        self.exportMasksButton.setObjectName(u"exportMasksButton")

        self.gridLayout.addWidget(self.exportMasksButton, 2, 0, 1, 1)

        self.exportContoursButton = QPushButton(self.groupBox)
        self.exportContoursButton.setObjectName(u"exportContoursButton")

        self.gridLayout.addWidget(self.exportContoursButton, 2, 1, 1, 1)


        self.verticalLayout.addWidget(self.groupBox)

        self.groupBox_4 = QGroupBox(self.frame)
        self.groupBox_4.setObjectName(u"groupBox_4")
        self.gridLayout_4 = QGridLayout(self.groupBox_4)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.hideContoursCheckBox = QCheckBox(self.groupBox_4)
        self.hideContoursCheckBox.setObjectName(u"hideContoursCheckBox")

        self.gridLayout_4.addWidget(self.hideContoursCheckBox, 3, 0, 1, 1)

        self.hidePointsCheckBox = QCheckBox(self.groupBox_4)
        self.hidePointsCheckBox.setObjectName(u"hidePointsCheckBox")

        self.gridLayout_4.addWidget(self.hidePointsCheckBox, 5, 1, 1, 1)

        self.hideNodesCheckBox = QCheckBox(self.groupBox_4)
        self.hideNodesCheckBox.setObjectName(u"hideNodesCheckBox")

        self.gridLayout_4.addWidget(self.hideNodesCheckBox, 6, 2, 1, 1)

        self.label_3 = QLabel(self.groupBox_4)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_4.addWidget(self.label_3, 3, 2, 1, 1)

        self.hideframesCheckBox = QCheckBox(self.groupBox_4)
        self.hideframesCheckBox.setObjectName(u"hideframesCheckBox")

        self.gridLayout_4.addWidget(self.hideframesCheckBox, 6, 0, 1, 1)

        self.label = QLabel(self.groupBox_4)
        self.label.setObjectName(u"label")

        self.gridLayout_4.addWidget(self.label, 1, 2, 1, 1)

        self.fpsSpinBox = QSpinBox(self.groupBox_4)
        self.fpsSpinBox.setObjectName(u"fpsSpinBox")
        self.fpsSpinBox.setMinimum(1)
        self.fpsSpinBox.setMaximum(60)
        self.fpsSpinBox.setSingleStep(5)
        self.fpsSpinBox.setValue(15)

        self.gridLayout_4.addWidget(self.fpsSpinBox, 1, 1, 1, 1)

        self.hideMasksCheckBox = QCheckBox(self.groupBox_4)
        self.hideMasksCheckBox.setObjectName(u"hideMasksCheckBox")

        self.gridLayout_4.addWidget(self.hideMasksCheckBox, 5, 0, 1, 1)

        self.hideHistogramCheckBox = QCheckBox(self.groupBox_4)
        self.hideHistogramCheckBox.setObjectName(u"hideHistogramCheckBox")
        self.hideHistogramCheckBox.setChecked(True)

        self.gridLayout_4.addWidget(self.hideHistogramCheckBox, 6, 1, 1, 1)

        self.lineWidthSpinBox = QSpinBox(self.groupBox_4)
        self.lineWidthSpinBox.setObjectName(u"lineWidthSpinBox")
        self.lineWidthSpinBox.setMinimum(1)
        self.lineWidthSpinBox.setMaximum(10)
        self.lineWidthSpinBox.setValue(3)

        self.gridLayout_4.addWidget(self.lineWidthSpinBox, 3, 1, 1, 1)

        self.hideSplinesCheckBox = QCheckBox(self.groupBox_4)
        self.hideSplinesCheckBox.setObjectName(u"hideSplinesCheckBox")

        self.gridLayout_4.addWidget(self.hideSplinesCheckBox, 5, 2, 1, 1)

        self.playButton = QPushButton(self.groupBox_4)
        self.playButton.setObjectName(u"playButton")

        self.gridLayout_4.addWidget(self.playButton, 0, 0, 2, 1)

        self.crossSectionComboBox = QComboBox(self.groupBox_4)
        self.crossSectionComboBox.setObjectName(u"crossSectionComboBox")

        self.gridLayout_4.addWidget(self.crossSectionComboBox, 7, 0, 1, 1)


        self.verticalLayout.addWidget(self.groupBox_4)

        self.groupBox_3 = QGroupBox(self.frame)
        self.groupBox_3.setObjectName(u"groupBox_3")
        self.horizontalLayout_2 = QHBoxLayout(self.groupBox_3)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.keyFramesListView = QListView(self.groupBox_3)
        self.keyFramesListView.setObjectName(u"keyFramesListView")

        self.horizontalLayout_2.addWidget(self.keyFramesListView)

        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.addKeyFrameButton = QPushButton(self.groupBox_3)
        self.addKeyFrameButton.setObjectName(u"addKeyFrameButton")

        self.verticalLayout_2.addWidget(self.addKeyFrameButton)

        self.deleteKeyFrameButton = QPushButton(self.groupBox_3)
        self.deleteKeyFrameButton.setObjectName(u"deleteKeyFrameButton")

        self.verticalLayout_2.addWidget(self.deleteKeyFrameButton)

        self.deleteAllKFButton = QPushButton(self.groupBox_3)
        self.deleteAllKFButton.setObjectName(u"deleteAllKFButton")

        self.verticalLayout_2.addWidget(self.deleteAllKFButton)

        self.label_7 = QLabel(self.groupBox_3)
        self.label_7.setObjectName(u"label_7")
        self.label_7.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_7)

        self.objIdSpinBox = QSpinBox(self.groupBox_3)
        self.objIdSpinBox.setObjectName(u"objIdSpinBox")
        self.objIdSpinBox.setMinimum(1)
        self.objIdSpinBox.setMaximum(10)
        self.objIdSpinBox.setValue(1)

        self.verticalLayout_2.addWidget(self.objIdSpinBox)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_2.addItem(self.verticalSpacer)


        self.horizontalLayout_2.addLayout(self.verticalLayout_2)


        self.verticalLayout.addWidget(self.groupBox_3)

        self.groupBox_2 = QGroupBox(self.frame)
        self.groupBox_2.setObjectName(u"groupBox_2")
        self.gridLayout_2 = QGridLayout(self.groupBox_2)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.segBackRangeButton = QPushButton(self.groupBox_2)
        self.segBackRangeButton.setObjectName(u"segBackRangeButton")

        self.gridLayout_2.addWidget(self.segBackRangeButton, 0, 1, 1, 1)

        self.segRangeButton = QPushButton(self.groupBox_2)
        self.segRangeButton.setObjectName(u"segRangeButton")

        self.gridLayout_2.addWidget(self.segRangeButton, 0, 2, 1, 1)

        self.customMaskCheckBox = QCheckBox(self.groupBox_2)
        self.customMaskCheckBox.setObjectName(u"customMaskCheckBox")

        self.gridLayout_2.addWidget(self.customMaskCheckBox, 2, 0, 1, 1)

        self.clearOutlineButton = QPushButton(self.groupBox_2)
        self.clearOutlineButton.setObjectName(u"clearOutlineButton")

        self.gridLayout_2.addWidget(self.clearOutlineButton, 2, 1, 1, 1)

        self.trackMaskButton = QPushButton(self.groupBox_2)
        self.trackMaskButton.setObjectName(u"trackMaskButton")

        self.gridLayout_2.addWidget(self.trackMaskButton, 2, 2, 1, 2)

        self.label_6 = QLabel(self.groupBox_2)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignTrailing|Qt.AlignmentFlag.AlignVCenter)

        self.gridLayout_2.addWidget(self.label_6, 1, 1, 1, 1)

        self.loClipSpinBox = QDoubleSpinBox(self.groupBox_2)
        self.loClipSpinBox.setObjectName(u"loClipSpinBox")
        self.loClipSpinBox.setDecimals(1)
        self.loClipSpinBox.setMaximum(49.500000000000000)
        self.loClipSpinBox.setSingleStep(0.500000000000000)
        self.loClipSpinBox.setValue(0.500000000000000)

        self.gridLayout_2.addWidget(self.loClipSpinBox, 1, 2, 1, 1)

        self.hiClipSpinBox = QDoubleSpinBox(self.groupBox_2)
        self.hiClipSpinBox.setObjectName(u"hiClipSpinBox")
        self.hiClipSpinBox.setDecimals(1)
        self.hiClipSpinBox.setMinimum(50.500000000000000)
        self.hiClipSpinBox.setMaximum(100.000000000000000)
        self.hiClipSpinBox.setSingleStep(0.500000000000000)
        self.hiClipSpinBox.setValue(99.500000000000000)

        self.gridLayout_2.addWidget(self.hiClipSpinBox, 1, 3, 1, 1)

        self.segSingleButton = QPushButton(self.groupBox_2)
        self.segSingleButton.setObjectName(u"segSingleButton")

        self.gridLayout_2.addWidget(self.segSingleButton, 0, 0, 1, 1)

        self.segAllButton = QPushButton(self.groupBox_2)
        self.segAllButton.setObjectName(u"segAllButton")

        self.gridLayout_2.addWidget(self.segAllButton, 0, 3, 1, 1)


        self.verticalLayout.addWidget(self.groupBox_2)

        self.groupBox_5 = QGroupBox(self.frame)
        self.groupBox_5.setObjectName(u"groupBox_5")
        self.gridLayout_5 = QGridLayout(self.groupBox_5)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.smoothSpinBox = QSpinBox(self.groupBox_5)
        self.smoothSpinBox.setObjectName(u"smoothSpinBox")
        self.smoothSpinBox.setMaximum(50)
        self.smoothSpinBox.setValue(5)

        self.gridLayout_5.addWidget(self.smoothSpinBox, 0, 1, 1, 1)

        self.label_4 = QLabel(self.groupBox_5)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_5.addWidget(self.label_4, 1, 2, 1, 1)

        self.contoursButton = QPushButton(self.groupBox_5)
        self.contoursButton.setObjectName(u"contoursButton")

        self.gridLayout_5.addWidget(self.contoursButton, 1, 0, 1, 1)

        self.epsilonSpinBox = QDoubleSpinBox(self.groupBox_5)
        self.epsilonSpinBox.setObjectName(u"epsilonSpinBox")
        self.epsilonSpinBox.setDecimals(1)
        self.epsilonSpinBox.setSingleStep(0.500000000000000)
        self.epsilonSpinBox.setValue(0.500000000000000)

        self.gridLayout_5.addWidget(self.epsilonSpinBox, 1, 1, 1, 1)

        self.fixMasksButton = QPushButton(self.groupBox_5)
        self.fixMasksButton.setObjectName(u"fixMasksButton")

        self.gridLayout_5.addWidget(self.fixMasksButton, 0, 0, 1, 1)

        self.label_2 = QLabel(self.groupBox_5)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout_5.addWidget(self.label_2, 0, 2, 1, 1)

        self.splinesButton = QPushButton(self.groupBox_5)
        self.splinesButton.setObjectName(u"splinesButton")

        self.gridLayout_5.addWidget(self.splinesButton, 2, 0, 1, 1)

        self.splineNodesSpinBox = QSpinBox(self.groupBox_5)
        self.splineNodesSpinBox.setObjectName(u"splineNodesSpinBox")
        self.splineNodesSpinBox.setMinimum(4)
        self.splineNodesSpinBox.setMaximum(50)
        self.splineNodesSpinBox.setValue(10)

        self.gridLayout_5.addWidget(self.splineNodesSpinBox, 2, 1, 1, 1)

        self.label_5 = QLabel(self.groupBox_5)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_5.addWidget(self.label_5, 2, 2, 1, 1)


        self.verticalLayout.addWidget(self.groupBox_5)


        self.horizontalLayout.addWidget(self.frame)

        self.horizontalLayout.setStretch(0, 6)
        self.horizontalLayout.setStretch(1, 1)
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1112, 22))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"Echo", None))
        self.groupBox.setTitle(QCoreApplication.translate("MainWindow", u"File", None))
        self.openDicomButton.setText(QCoreApplication.translate("MainWindow", u"Open DICOM", None))
#if QT_CONFIG(tooltip)
        self.loadKeyFramesButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Load keyframes from a file</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.loadKeyFramesButton.setText(QCoreApplication.translate("MainWindow", u"Load KFs", None))
#if QT_CONFIG(tooltip)
        self.saveKeyFramesButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Save keyframes to a file</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.saveKeyFramesButton.setText(QCoreApplication.translate("MainWindow", u"Save KFs", None))
        self.exportMasksButton.setText(QCoreApplication.translate("MainWindow", u"Export masks", None))
        self.exportContoursButton.setText(QCoreApplication.translate("MainWindow", u"Export contours", None))
        self.groupBox_4.setTitle(QCoreApplication.translate("MainWindow", u"View", None))
        self.hideContoursCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide contours", None))
        self.hidePointsCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide points", None))
        self.hideNodesCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide nodes", None))
        self.label_3.setText(QCoreApplication.translate("MainWindow", u"line width", None))
        self.hideframesCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide frames", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"fps", None))
        self.hideMasksCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide masks", None))
        self.hideHistogramCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide hist", None))
        self.hideSplinesCheckBox.setText(QCoreApplication.translate("MainWindow", u"hide splines", None))
        self.playButton.setText(QCoreApplication.translate("MainWindow", u"Play", None))
        self.groupBox_3.setTitle(QCoreApplication.translate("MainWindow", u"Keyframes", None))
#if QT_CONFIG(tooltip)
        self.addKeyFrameButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Add selected frame to keyframes</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.addKeyFrameButton.setText(QCoreApplication.translate("MainWindow", u"Add KF", None))
#if QT_CONFIG(tooltip)
        self.deleteKeyFrameButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Remove selected keyframe</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.deleteKeyFrameButton.setText(QCoreApplication.translate("MainWindow", u"Remove KF", None))
        self.deleteAllKFButton.setText(QCoreApplication.translate("MainWindow", u"Clear all", None))
        self.label_7.setText(QCoreApplication.translate("MainWindow", u"object ID", None))
#if QT_CONFIG(tooltip)
        self.objIdSpinBox.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Object ID</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.groupBox_2.setTitle(QCoreApplication.translate("MainWindow", u"Segment", None))
#if QT_CONFIG(tooltip)
        self.segBackRangeButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Segment from selected keyframe to previous keyframe</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.segBackRangeButton.setText(QCoreApplication.translate("MainWindow", u"\u2b05\ufe0f backward", None))
#if QT_CONFIG(tooltip)
        self.segRangeButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Segment from selected keyframe to next keyframe</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.segRangeButton.setText(QCoreApplication.translate("MainWindow", u"\u27a1\ufe0f forward", None))
#if QT_CONFIG(tooltip)
        self.customMaskCheckBox.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Custom mask outline on the selected keyframe. Click adds a vertex, drag a vertex to move it, Shift-click inserts a vertex on the nearest edge, Ctrl-click removes the nearest vertex.</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.customMaskCheckBox.setText(QCoreApplication.translate("MainWindow", u"custom mask", None))
#if QT_CONFIG(tooltip)
        self.clearOutlineButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Clear the custom mask outline of the active object on this frame</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.clearOutlineButton.setText(QCoreApplication.translate("MainWindow", u"clear outline", None))
#if QT_CONFIG(tooltip)
        self.trackMaskButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Track custom mask outlines from selected keyframe backward and forward</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.trackMaskButton.setText(QCoreApplication.translate("MainWindow", u"track mask", None))
        self.label_6.setText(QCoreApplication.translate("MainWindow", u"clip", None))
#if QT_CONFIG(tooltip)
        self.segSingleButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Segment selected keyframe</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.segSingleButton.setText(QCoreApplication.translate("MainWindow", u"\u2b07\ufe0f single", None))
#if QT_CONFIG(tooltip)
        self.segAllButton.setToolTip(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Segment all the frames</p></body></html>", None))
#endif // QT_CONFIG(tooltip)
        self.segAllButton.setText(QCoreApplication.translate("MainWindow", u"\u2194\ufe0f all", None))
        self.groupBox_5.setTitle(QCoreApplication.translate("MainWindow", u"Masks", None))
        self.label_4.setText(QCoreApplication.translate("MainWindow", u"approx epsilon", None))
        self.contoursButton.setText(QCoreApplication.translate("MainWindow", u"Get contours", None))
        self.fixMasksButton.setText(QCoreApplication.translate("MainWindow", u"Fix masks", None))
        self.label_2.setText(QCoreApplication.translate("MainWindow", u"smooth level", None))
        self.splinesButton.setText(QCoreApplication.translate("MainWindow", u"Get splines", None))
        self.label_5.setText(QCoreApplication.translate("MainWindow", u"control points", None))
    # retranslateUi

