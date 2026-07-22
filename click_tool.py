from qgis.gui import QgsMapTool
from qgis.PyQt.QtCore import Qt


class ClickTool(QgsMapTool):
    def __init__(
        self,
        iface,
        left_click_callback,
        right_click_callback=None,
        escape_callback=None,
        deactivated_callback=None,
    ):
        QgsMapTool.__init__(self, iface.mapCanvas())
        self.iface = iface
        self.left_click_callback = left_click_callback
        self.right_click_callback = right_click_callback
        self.escape_callback = escape_callback
        self.deactivated_callback = deactivated_callback
        self.canvas = iface.mapCanvas()

    @staticmethod
    def _device_point(e):
        # QMouseEvent.pos() is deprecated in Qt6; position() exists in Qt6 only
        if hasattr(e, "position"):
            return e.position().toPoint()
        return e.pos()

    def canvasPressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.left_click_callback(self._device_point(e))
        elif e.button() == Qt.MouseButton.RightButton:
            if self.right_click_callback is not None:
                self.right_click_callback(self._device_point(e))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.escape_callback is not None:
                self.escape_callback()
            return
        QgsMapTool.keyPressEvent(self, e)

    def deactivate(self):
        QgsMapTool.deactivate(self)
        if self.deactivated_callback is not None:
            self.deactivated_callback()
