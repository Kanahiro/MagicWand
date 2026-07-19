import os.path

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

DEFAULT_THRESHOLD = 50


def configure_threshold_slider(slider: QSlider) -> None:
    slider.setMinimum(10)
    slider.setMaximum(90)
    slider.setSingleStep(10)


class MagicwandDockWidget(QDockWidget):
    closingPlugin = pyqtSignal()

    def __init__(self, parent=None):
        """Constructor."""
        super().__init__(parent)
        self.setObjectName("MagicwandDockWidgetBase")
        self.setWindowTitle("Magic Wand")

        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.start_button = QPushButton()
        self.start_button.setIcon(QIcon(icon_path))
        self.start_button.setToolTip("Start Magic Wand")
        self.layerComboBox = QComboBox()
        self.skip_preview_checkbox = QCheckBox("Skip Preview")
        self.skip_preview_checkbox.setToolTip(
            "Create polygons immediately on click, without the tentative "
            "polygon and its confirmation dialog"
        )
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        configure_threshold_slider(self.threshold_slider)
        self.threshold_slider.setValue(DEFAULT_THRESHOLD)
        self.threshold_slider.setToolTip("Color Threshold")
        self.threshold_slider.setMinimumWidth(100)
        self.layerComboBox.setToolTip("Output Layer")
        self.layerComboBox.setMinimumWidth(120)

        # everything on a single compact row
        layout = QHBoxLayout()
        layout.addWidget(self.start_button)
        layout.addWidget(QLabel("Output"))
        layout.addWidget(self.layerComboBox, 1)
        layout.addSpacing(12)
        layout.addWidget(QLabel("Ambiguous"))
        layout.addWidget(self.threshold_slider, 1)
        layout.addWidget(QLabel("Strict"))
        layout.addSpacing(12)
        layout.addWidget(self.skip_preview_checkbox)

        contents = QWidget()
        contents.setLayout(layout)
        self.setWidget(contents)

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()
