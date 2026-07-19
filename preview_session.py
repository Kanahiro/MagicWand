import numpy as np

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsPointXY,
    QgsProject,
)
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import QPoint
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QDialog

from .confirm_dialog import ConfirmDialog
from .image_analyzer import ImageAnalyzer
from .polygon_maker import PixelGrid, PolygonMaker

SEED_MARKER_COLOR = QColor(255, 140, 0)

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
    """Union of the magic-wand selections of all seed points, polygonized.

    Masks are OR-combined before polygonization, so overlapping
    selections dissolve into one polygon and disjoint ones become
    separate features.
    """
    threshold = 100 - slider_value
    to_pixel = grid.getCoordinateTransform()

    mask: np.ndarray | None = None
    for map_point in seeds:
        device = to_pixel.transform(map_point)
        seed_mask = analyzer.to_binary(
            QPoint(int(device.x()), int(device.y())), threshold
        )
        mask = seed_mask if mask is None else mask | seed_mask

    if mask is None or not mask.any():
        return []
    return PolygonMaker(grid, mask).build_polygons(crs)


class PreviewSession:
    """One click-to-confirm interaction.

    Owns the canvas snapshot taken at the first click, the seed points
    (in map coordinates, so panning during the session cannot corrupt
    them), the seed markers, and the confirm dialog. While the session
    is open the dock widget is locked; the dialog's Add Point button
    hands one click back to the map canvas to add a seed.
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
        self.awaiting_point = False

        self.dialog = ConfirmDialog(
            plugin.dockwidget.threshold_slider.value(),
            self.on_threshold_changed,
            parent=plugin.iface.mainWindow(),
        )
        self.dialog.add_point_button.clicked.connect(self.wait_for_point)
        self.dialog.finished.connect(self.on_finished)

        plugin.dockwidget.setEnabled(False)
        self.add_seed(first_widget_point)
        self.dialog.show()

    # ------------------------------------------------------------- seeds

    def handle_canvas_click(self, widget_point: QPoint) -> None:
        """Canvas clicks reach the session only through the map tool;
        they are ignored unless Add Point armed the session for one."""
        if not self.awaiting_point:
            return
        self.awaiting_point = False
        self.dialog.set_waiting_for_point(False)
        self.add_seed(widget_point)

    def wait_for_point(self) -> None:
        self.awaiting_point = True
        self.dialog.set_waiting_for_point(True)

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

    # ---------------------------------------------------------- recompute

    def on_threshold_changed(self, _slider_value: int) -> None:
        self.recompute()

    def recompute(self) -> None:
        self.features = build_multi_seed_features(
            self.analyzer, self.grid, self.seeds, self.dialog.threshold(), self.crs
        )
        self.plugin.show_tentative(self.features)

    # ------------------------------------------------------------- finish

    def cancel(self) -> None:
        self.dialog.reject()

    def on_finished(self, result: int) -> None:
        for marker in self.markers:
            self.canvas.scene().removeItem(marker)
        self.markers = []

        self.plugin.hide_tentative()
        self.plugin.dockwidget.setEnabled(True)
        self.plugin.preview_session = None
        self.dialog.deleteLater()

        if result == QDialog.DialogCode.Accepted and self.features:
            # keep the confirmed threshold as the new default
            self.plugin.dockwidget.threshold_slider.setValue(self.dialog.threshold())
            self.plugin.save_features(self.features, self.crs)
