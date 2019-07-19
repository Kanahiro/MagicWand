from qgis.core import *
from qgis.gui import *
from qgis.PyQt.QtCore import QPoint

class ClickTool(QgsMapTool):
    def __init__(self, iface, callback):
        QgsMapTool.__init__(self,iface.mapCanvas())
        self.iface      = iface
        self.callback   = callback
        self.canvas     = iface.mapCanvas()
        self.drugging = False
        return None

    def canvasPressEvent(self,e):
        self.drugging = True
        point = QPoint(e.pos().x(),e.pos().y())
        self.callback(point)
        return None

    def canvasMoveEvent(self,e):
        if self.drugging == False:
            return None
        point = QPoint(e.pos().x(),e.pos().y())
        self.callback(point)
        return None

    def canvasReleaseEvent(self,e):
        point = QPoint(e.pos().x(),e.pos().y())
        self.callback(point)
        self.drugging = False
        return None