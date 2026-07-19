"""Unit tests for MagicwandDockWidget (requires a Qt environment)."""

from plugin_dir.magic_wand_dockwidget import DEFAULT_THRESHOLD, MagicwandDockWidget


class TestMagicwandDockWidget:
    def test_defaults(self, qgis_app):
        dock = MagicwandDockWidget()

        assert dock.threshold_slider.value() == DEFAULT_THRESHOLD
        assert dock.threshold_slider.minimum() == 10
        assert dock.threshold_slider.maximum() == 90
        # the confirm flow is the default; Skip Preview is opt-in
        assert not dock.skip_preview_checkbox.isChecked()
        # the start button carries no on/off state, it just activates the tool
        assert dock.start_button.text() == "Start Magic Wand"
