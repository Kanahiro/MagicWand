"""Unit tests for MagicwandDockWidget (requires a Qt environment)."""

from plugin_dir.magic_wand_dockwidget import DEFAULT_THRESHOLD, MagicwandDockWidget


class TestMagicwandDockWidget:
    def test_defaults(self, qgis_app):
        dock = MagicwandDockWidget()

        assert dock.threshold_slider.value() == DEFAULT_THRESHOLD
        assert dock.threshold_slider.minimum() == 10
        assert dock.threshold_slider.maximum() == 90
        # the confirm flow is the default; 1 click mode is opt-in
        assert not dock.one_click_checkbox.isChecked()
        # the start button is icon-only; the tooltip names the action
        assert dock.start_button.text() == ""
        assert not dock.start_button.icon().isNull()
        assert dock.start_button.toolTip() == "Start Magic Wand"
