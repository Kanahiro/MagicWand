from qgis.gui import QgsMapTool


class ClickTool(QgsMapTool):
    def __init__(self, iface, callback):
        QgsMapTool.__init__(self, iface.mapCanvas())
        self.iface = iface
        self.callback = callback
        self.canvas = iface.mapCanvas()

    def canvasPressEvent(self, e):
        # QMouseEvent.pos() is deprecated in Qt6; position() exists in Qt6 only
        if hasattr(e, 'position'):
            point = e.position().toPoint()
        else:
            point = e.pos()
        self.callback(point)
