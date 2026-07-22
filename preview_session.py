from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsPointXY,
    QgsProject,
)
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import QPoint, QTimer
from qgis.PyQt.QtGui import QColor

from .image_analyzer import ImageAnalyzer
from .polygon_maker import PixelGrid, PolygonMaker

SEED_MARKER_COLOR = QColor(255, 140, 0)

# slider changes are applied to the tentative polygon after this delay,
# so dragging the slider does not recompute on every step
RECOMPUTE_DELAY_MS = 150

# unscoped in Qt5 builds, scoped in Qt6 builds
ICON_X = getattr(QgsVertexMarker, "ICON_X", None)
if ICON_X is None:
    ICON_X = QgsVertexMarker.IconType.ICON_X


def build_multi_seed_features(
    analyzer: ImageAnalyzer,
    grid: PixelGrid,
    seeds: list[QgsPointXY],
    slider_value: int,
    crs: QgsCoordinateReferenceSystem,
) -> list[QgsFeature]:
    """The magic-wand selection of all seed points together, polygonized.

    The seed colors form one combined color model and the flood fill
    grows from all points at once (see ImageAnalyzer.mask_from_bgr_multi):
    overlapping selections dissolve into one polygon and disjoint ones
    become separate features.
    """
    if not seeds:
        return []

    threshold = 100 - slider_value
    to_pixel = grid.getCoordinateTransform()
    points = []
    for map_point in seeds:
        device = to_pixel.transform(map_point)
        points.append(QPoint(int(device.x()), int(device.y())))

    mask = analyzer.to_binary_multi(points, threshold)
    if not mask.any():
        return []
    return PolygonMaker(grid, mask).build_polygons(crs)


class PreviewSession:
    """A right-click-to-preview, left-click-to-confirm interaction.

    Owns the canvas snapshot taken at the first right click and the seed
    points (in map coordinates, so panning during the session cannot
    corrupt them). Every further right click adds a seed point to the
    selection, moving the dock widget's Color Threshold slider updates
    the tentative polygon live, a left click confirms and saves it, and
    Escape (or deactivating the tool) discards it. Backspace undoes the
    latest seed point; undoing the only one ends the session.
    """

    def __init__(self, plugin, image, first_widget_point: QPoint):
        self.plugin = plugin
        self.canvas = plugin.canvas
        self.analyzer = ImageAnalyzer(image)
        self.grid = PixelGrid(
            image.width(),
            image.height(),
            self.canvas.mapSettings().visibleExtent(),
        )
        self.crs = QgsProject.instance().crs()
        self.seeds: list[QgsPointXY] = []
        self.markers: list[QgsVertexMarker] = []
        self.features: list[QgsFeature] = []
        self.finished = False

        # the dock widget slider drives the preview directly, debounced
        # so dragging it does not recompute on every step
        self.threshold_slider = plugin.dockwidget.threshold_slider
        self._recompute_timer = QTimer(self.canvas)
        self._recompute_timer.setSingleShot(True)
        self._recompute_timer.timeout.connect(self.recompute)
        self.threshold_slider.valueChanged.connect(self._schedule_recompute)

        self.add_seed(first_widget_point)

    def threshold(self) -> int:
        return self.threshold_slider.value()

    # ------------------------------------------------------------- seeds

    def add_seed(self, widget_point: QPoint) -> None:
        # record the seed in map coordinates: the snapshot transform
        # keeps it valid even if the canvas is panned meanwhile
        map_point = self.canvas.getCoordinateTransform().toMapCoordinatesF(
            widget_point.x(), widget_point.y()
        )
        self.seeds.append(map_point)

        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(map_point)
        marker.setIconType(ICON_X)
        marker.setColor(SEED_MARKER_COLOR)
        marker.setPenWidth(2)
        self.markers.append(marker)

        self.recompute()

    def remove_last_seed(self) -> None:
        """Undo the latest right click; removing the only seed ends the
        session."""
        if not self.seeds:
            return
        self.seeds.pop()
        self.canvas.scene().removeItem(self.markers.pop())

        if not self.seeds:
            self.cancel()
            return
        self.recompute()

    # ---------------------------------------------------------- recompute

    def _schedule_recompute(self, _value: int) -> None:
        self._recompute_timer.start(RECOMPUTE_DELAY_MS)

    def recompute(self) -> None:
        self.features = build_multi_seed_features(
            self.analyzer, self.grid, self.seeds, self.threshold(), self.crs
        )
        self.plugin.show_tentative(self.features)

    # ------------------------------------------------------------- finish

    def confirm(self) -> None:
        features, crs = self.features, self.crs
        self._finish()
        if features:
            self.plugin.save_features(features, crs)

    def cancel(self) -> None:
        self._finish()

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True

        self.threshold_slider.valueChanged.disconnect(self._schedule_recompute)
        self._recompute_timer.stop()
        self._recompute_timer.deleteLater()

        for marker in self.markers:
            self.canvas.scene().removeItem(marker)
        self.markers = []

        self.plugin.hide_tentative()
        self.plugin.preview_session = None
