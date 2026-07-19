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
    """One click-to-confirm interaction.

    Owns the canvas snapshot taken at the first click, the seed points
    (in map coordinates, so panning during the session cannot corrupt
    them), the seed markers, and the confirm dialog. The dialog stays
    on top while the rest of the UI remains usable; every further map
    click adds a seed point to the selection.
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

        self.dialog = ConfirmDialog(
            plugin.dockwidget.threshold_slider.value(),
            self.on_threshold_changed,
            parent=plugin.iface.mainWindow(),
        )
        self.dialog.finished.connect(self.on_finished)

        self.add_seed(first_widget_point)
        self.dialog.show()

    # ------------------------------------------------------------- seeds

    def handle_canvas_click(self, widget_point: QPoint) -> None:
        """Every canvas click while the session is open adds a seed
        point to the selection."""
        self.add_seed(widget_point)

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
        self.plugin.preview_session = None
        self.dialog.deleteLater()

        if result == QDialog.DialogCode.Accepted and self.features:
            # keep the confirmed threshold as the new default
            self.plugin.dockwidget.threshold_slider.setValue(self.dialog.threshold())
            self.plugin.save_features(self.features, self.crs)
