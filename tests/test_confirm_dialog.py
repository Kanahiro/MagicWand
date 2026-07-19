"""Unit tests for ConfirmDialog (requires a Qt environment)."""

from plugin_dir.confirm_dialog import RECOMPUTE_DELAY_MS, ConfirmDialog
from qgis.PyQt.QtTest import QTest


class TestConfirmDialog:
    def test_initial_threshold(self, qgis_app):
        dialog = ConfirmDialog(70, lambda value: None)
        assert dialog.threshold() == 70

    def test_threshold_changes_are_debounced(self, qgis_app):
        received = []
        dialog = ConfirmDialog(50, received.append)

        dialog.threshold_slider.setValue(30)
        dialog.threshold_slider.setValue(70)
        assert received == []  # nothing until the debounce delay passes

        QTest.qWait(RECOMPUTE_DELAY_MS + 100)
        assert received == [70]  # one callback with the final value

    def test_slider_uses_shared_configuration(self, qgis_app):
        dialog = ConfirmDialog(50, lambda value: None)
        assert dialog.threshold_slider.minimum() == 10
        assert dialog.threshold_slider.maximum() == 90

    def test_waiting_for_point_state(self, qgis_app):
        dialog = ConfirmDialog(50, lambda value: None)

        dialog.set_waiting_for_point(True)
        assert not dialog.threshold_slider.isEnabled()
        assert not dialog.add_point_button.isEnabled()
        assert dialog.add_point_button.text() != "Add Point"

        dialog.set_waiting_for_point(False)
        assert dialog.threshold_slider.isEnabled()
        assert dialog.add_point_button.isEnabled()
        assert dialog.add_point_button.text() == "Add Point"
