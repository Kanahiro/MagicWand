from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from .magic_wand_dockwidget import configure_threshold_slider

# slider changes are applied to the tentative polygon after this delay,
# so dragging the slider does not recompute on every step
RECOMPUTE_DELAY_MS = 150

ADD_POINT_LABEL = "Add Point"
WAITING_FOR_POINT_LABEL = "Click on the map…"


class ConfirmDialog(QDialog):
    """Dialog shown while the tentative polygon is displayed.

    The rest of the UI is locked while it is open; the Color Threshold
    can still be adjusted (the tentative polygon is recomputed) before
    the polygon is confirmed with OK or discarded with Cancel. The Add
    Point button temporarily hands control back to the map canvas so an
    additional seed point can be clicked into the selection.
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

        self.add_point_button = QPushButton(ADD_POINT_LABEL)
        self.add_point_button.setToolTip(
            "Click the map to add another seed point to the selection"
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.addButton(self.add_point_button, QDialogButtonBox.ButtonRole.ActionRole)
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

    def set_waiting_for_point(self, waiting: bool) -> None:
        """While waiting, the threshold controls are inert and the Add
        Point button tells the user to click the map; OK/Cancel stay
        available."""
        self.threshold_slider.setEnabled(not waiting)
        self.add_point_button.setEnabled(not waiting)
        self.add_point_button.setText(
            WAITING_FOR_POINT_LABEL if waiting else ADD_POINT_LABEL
        )

    def _schedule_recompute(self, _value: int) -> None:
        self._recompute_timer.start(RECOMPUTE_DELAY_MS)

    def _emit_threshold_changed(self) -> None:
        self._on_threshold_changed(self.threshold_slider.value())
