from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QGridLayout,
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

        self.enable_button = QPushButton("Enable")
        self.layerComboBox = QComboBox()
        self.skip_preview_checkbox = QCheckBox("Skip Preview")
        self.skip_preview_checkbox.setToolTip(
            "Create polygons immediately on click, without the tentative "
            "polygon and its confirmation dialog"
        )
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        configure_threshold_slider(self.threshold_slider)
        self.threshold_slider.setValue(DEFAULT_THRESHOLD)

        layout = QGridLayout()
        layout.addWidget(self.enable_button, 0, 0)
        layout.addWidget(self.layerComboBox, 0, 1, 1, 2)
        layout.addWidget(self.skip_preview_checkbox, 0, 3)

        layout.addWidget(QLabel("Color Threshold"), 1, 0)
        layout.addWidget(QLabel("Ambiguous"), 1, 1)
        layout.addWidget(self.threshold_slider, 1, 2)
        layout.addWidget(QLabel("Strict"), 1, 3)

        contents = QWidget()
        contents.setLayout(layout)
        self.setWidget(contents)

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()
