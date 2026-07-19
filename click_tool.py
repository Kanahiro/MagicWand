from qgis.gui import QgsMapTool


class ClickTool(QgsMapTool):
    def __init__(
        self,
        iface,
        click_callback,
        move_callback=None,
        deactivated_callback=None,
    ):
        QgsMapTool.__init__(self, iface.mapCanvas())
        self.iface = iface
        self.click_callback = click_callback
        self.move_callback = move_callback
        self.deactivated_callback = deactivated_callback
        self.canvas = iface.mapCanvas()

    @staticmethod
    def _device_point(e):
        # QMouseEvent.pos() is deprecated in Qt6; position() exists in Qt6 only
        if hasattr(e, "position"):
            return e.position().toPoint()
        return e.pos()

    def canvasPressEvent(self, e):
        self.click_callback(self._device_point(e))

    def canvasMoveEvent(self, e):
        if self.move_callback is not None:
            self.move_callback(self._device_point(e))

    def deactivate(self):
        QgsMapTool.deactivate(self)
        if self.deactivated_callback is not None:
            self.deactivated_callback()
