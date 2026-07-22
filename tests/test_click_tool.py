"""Unit tests for ClickTool event dispatch (requires QGIS)."""

from plugin_dir.click_tool import ClickTool
from qgis.PyQt.QtCore import QPoint, Qt


class FakeMouseEvent:
    def __init__(self, button, point=QPoint(3, 7)):
        self._button = button
        self._point = point

    def button(self):
        return self._button

    def pos(self):
        return self._point


class FakeKeyEvent:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key

    def ignore(self):
        pass


class TestClickTool:
    def _tool(self, qgis_iface):
        calls = {"left": [], "right": [], "escape": 0, "backspace": 0}

        def count(key):
            return lambda: calls.__setitem__(key, calls[key] + 1)

        tool = ClickTool(
            qgis_iface,
            left_click_callback=calls["left"].append,
            right_click_callback=calls["right"].append,
            escape_callback=count("escape"),
            backspace_callback=count("backspace"),
        )
        return tool, calls

    def test_left_click_dispatch(self, qgis_iface):
        tool, calls = self._tool(qgis_iface)
        tool.canvasPressEvent(FakeMouseEvent(Qt.MouseButton.LeftButton))
        assert calls["left"] == [QPoint(3, 7)]
        assert calls["right"] == []

    def test_right_click_dispatch(self, qgis_iface):
        tool, calls = self._tool(qgis_iface)
        tool.canvasPressEvent(FakeMouseEvent(Qt.MouseButton.RightButton))
        assert calls["right"] == [QPoint(3, 7)]
        assert calls["left"] == []

    def test_escape_dispatch(self, qgis_iface):
        tool, calls = self._tool(qgis_iface)
        tool.keyPressEvent(FakeKeyEvent(Qt.Key.Key_Escape))
        assert calls["escape"] == 1
        assert calls["backspace"] == 0

    def test_backspace_dispatch(self, qgis_iface):
        tool, calls = self._tool(qgis_iface)
        tool.keyPressEvent(FakeKeyEvent(Qt.Key.Key_Backspace))
        assert calls["backspace"] == 1
        assert calls["escape"] == 0

    def test_optional_callbacks_default_to_none(self, qgis_iface):
        tool = ClickTool(qgis_iface, left_click_callback=lambda p: None)
        # none of these must raise without the optional callbacks
        tool.canvasPressEvent(FakeMouseEvent(Qt.MouseButton.RightButton))
        tool.keyPressEvent(FakeKeyEvent(Qt.Key.Key_Escape))
        tool.keyPressEvent(FakeKeyEvent(Qt.Key.Key_Backspace))
