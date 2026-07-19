from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QSlider,
)

from .magic_wand_dockwidget import configure_threshold_slider

# slider changes are applied to the tentative polygon after this delay,
# so dragging the slider does not recompute on every step
RECOMPUTE_DELAY_MS = 150


class ConfirmDialog(QDialog):
    """Modal dialog shown while the tentative polygon is displayed.

    It locks the rest of the UI; the Color Threshold can still be
    adjusted (the tentative polygon is recomputed) before the polygon
    is confirmed with OK or discarded with Cancel.
    """

    def __init__(self, threshold_value: int, on_threshold_changed, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Magic Wand")
        self._on_threshold_changed = on_threshold_changed

        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        configure_threshold_slider(self.threshold_slider)
        self.threshold_slider.setValue(threshold_value)

        self._recompute_timer = QTimer(self)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.timeout.connect(self._emit_threshold_changed)
        self.threshold_slider.valueChanged.connect(self._schedule_recompute)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QGridLayout()
        layout.addWidget(QLabel("Color Threshold"), 0, 0, 1, 3)
        layout.addWidget(QLabel("Ambiguous"), 1, 0)
        layout.addWidget(self.threshold_slider, 1, 1)
        layout.addWidget(QLabel("Strict"), 1, 2)
        layout.addWidget(buttons, 2, 0, 1, 3)
        self.setLayout(layout)

    def threshold(self) -> int:
        return self.threshold_slider.value()

    def _schedule_recompute(self, _value: int) -> None:
        self._recompute_timer.start(RECOMPUTE_DELAY_MS)

    def _emit_threshold_changed(self) -> None:
        self._on_threshold_changed(self.threshold_slider.value())
