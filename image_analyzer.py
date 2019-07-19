from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject, QgsMapLayer, QgsRectangle, QgsPoint, QgsMultiBandColorRenderer, QgsRaster

import numpy as np
import cv2

class ImageAnalyzer:
    def __init__(self, image):
        self.image = image

    def to_nparray(self):
        image = self.image.convertToFormat(4)

        width = image.width()
        height = image.height()

        ptr = image.bits()
        ptr.setsize(image.byteCount())
        arr = np.array(ptr).reshape(height, width, 4)
        return arr

    def get_rgb(self, point):
        return self.image.pixelColor(point.x(), point.y()).rgba()

    def make_polygon(self, point):
        polygon = None
        return polygon