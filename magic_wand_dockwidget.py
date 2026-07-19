# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)


class MagicwandDockWidget(QDockWidget):
    closingPlugin = pyqtSignal()

    def __init__(self, parent=None):
        """Constructor."""
        super().__init__(parent)
        self.setObjectName("MagicwandDockWidgetBase")
        self.setWindowTitle("Magic Wand")

        self.enable_button = QPushButton("Enable")
        self.layerComboBox = QComboBox()
        self.accuracy_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)

        layout = QGridLayout()
        layout.addWidget(self.enable_button, 0, 0)
        layout.addWidget(self.layerComboBox, 0, 1, 1, 3)

        layout.addWidget(QLabel("Accuracy"), 1, 0)
        layout.addWidget(QLabel("Fast"), 1, 1)
        layout.addWidget(self.accuracy_slider, 1, 2)
        layout.addWidget(QLabel("Precise"), 1, 3)

        layout.addWidget(QLabel("Color Threshold"), 2, 0)
        layout.addWidget(QLabel("Ambiguous"), 2, 1)
        layout.addWidget(self.threshold_slider, 2, 2)
        layout.addWidget(QLabel("Strict"), 2, 3)

        contents = QWidget()
        contents.setLayout(layout)
        self.setWidget(contents)

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()
