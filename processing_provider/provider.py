import os.path

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .polygonize_algorithm import PolygonizeBySeedsAlgorithm


class MagicWandProvider(QgsProcessingProvider):
    def id(self) -> str:
        return "magicwand"

    def name(self) -> str:
        return "Magic Wand"

    def icon(self) -> QIcon:
        return QIcon(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.png")
        )

    def loadAlgorithms(self) -> None:
        self.addAlgorithm(PolygonizeBySeedsAlgorithm())
