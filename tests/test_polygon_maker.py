"""Unit tests for PolygonMaker (requires a QGIS environment)."""

import math

import numpy as np
import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

CRS = QgsCoordinateReferenceSystem("EPSG:3857")

ROTATION = 30  # degrees, used by the rotated-canvas tests


def rotated_envelope(width: float, height: float, rotation: float) -> QgsRectangle:
    """Axis-aligned envelope of a width x height view centered on
    (width/2, height/2) rotated by `rotation` degrees, as
    QgsMapCanvas.visibleExtent() reports it for a rotated canvas."""
    angle = math.radians(rotation)
    env_width = width * abs(math.cos(angle)) + height * abs(math.sin(angle))
    env_height = width * abs(math.sin(angle)) + height * abs(math.cos(angle))
    center_x, center_y = width / 2, height / 2
    return QgsRectangle(
        center_x - env_width / 2,
        center_y - env_height / 2,
        center_x + env_width / 2,
        center_y + env_height / 2,
    )


@pytest.fixture
def canvas(qgis_app, polygon_maker_module):
    # PixelGrid stands in for the map canvas (a real QgsMapCanvas widget
    # defers resize handling to its event loop, which makes pixel<->map
    # transforms unpredictable in headless tests).
    # 200x100 px grid showing a 200x100 map-unit extent -> 1 unit/px
    return polygon_maker_module.PixelGrid(200, 100, QgsRectangle(0, 0, 200, 100))


@pytest.fixture
def rotated_canvas(qgis_app, polygon_maker_module):
    # the same 200x100 px grid at 1 unit/px, rotated by 30 degrees; the
    # extent is the envelope of the rotated view, like visibleExtent()
    return polygon_maker_module.PixelGrid(
        200, 100, rotated_envelope(200, 100, ROTATION), rotation=ROTATION
    )


@pytest.fixture
def polygon_maker_module(qgis_plugin_path):
    from plugin_dir import polygon_maker

    return polygon_maker


class TestPolygonizeMask:
    def test_single_region(self, polygon_maker_module):
        mask = np.zeros((10, 20), dtype=bool)
        mask[2:8, 3:12] = True

        polygons = polygon_maker_module.polygonize_mask(mask)

        assert len(polygons) == 1
        rings = polygons[0]
        assert len(rings) == 1  # no holes
        assert polygon_maker_module.ring_area(rings[0]) == pytest.approx(54)
        # ring vertices are cell corners of the mask block
        assert rings[0][:, 0].min() == 3
        assert rings[0][:, 0].max() == 12
        assert rings[0][:, 1].min() == 2
        assert rings[0][:, 1].max() == 8

    def test_hole_is_traced_as_interior_ring(self, polygon_maker_module):
        mask = np.zeros((20, 20), dtype=bool)
        mask[1:19, 1:19] = True
        mask[5:15, 5:15] = False  # 10x10 hole

        polygons = polygon_maker_module.polygonize_mask(mask)

        assert len(polygons) == 1
        rings = polygons[0]
        assert len(rings) == 2
        assert polygon_maker_module.ring_area(rings[0]) == pytest.approx(18 * 18)
        assert polygon_maker_module.ring_area(rings[1]) == pytest.approx(100)

    def test_disjoint_regions_are_separate_polygons(self, polygon_maker_module):
        mask = np.zeros((10, 20), dtype=bool)
        mask[1:4, 1:4] = True
        mask[6:9, 10:15] = True

        polygons = polygon_maker_module.polygonize_mask(mask)

        assert len(polygons) == 2
        areas = sorted(polygon_maker_module.ring_area(p[0]) for p in polygons)
        assert areas == pytest.approx([9, 15])

    def test_diagonal_neighbors_are_not_connected(self, polygon_maker_module):
        # the mask comes from a 4-connected flood fill; tracing must not
        # merge cells that only touch at a corner
        mask = np.zeros((4, 4), dtype=bool)
        mask[1, 1] = True
        mask[2, 2] = True

        polygons = polygon_maker_module.polygonize_mask(mask)

        assert len(polygons) == 2

    def test_diagonal_holes_stay_separate_rings(self, polygon_maker_module):
        mask = np.ones((6, 6), dtype=bool)
        mask[2, 2] = False
        mask[3, 3] = False  # touches the first hole only at a corner

        polygons = polygon_maker_module.polygonize_mask(mask)

        assert len(polygons) == 1
        rings = polygons[0]
        assert len(rings) == 3  # exterior + two one-cell holes
        assert polygon_maker_module.ring_area(rings[1]) == pytest.approx(1)
        assert polygon_maker_module.ring_area(rings[2]) == pytest.approx(1)

    def test_empty_mask(self, polygon_maker_module):
        mask = np.zeros((10, 20), dtype=bool)

        assert polygon_maker_module.polygonize_mask(mask) == []


class TestRotatedCanvas:
    def test_map_units_per_pixel_ignores_envelope_growth(self, rotated_canvas):
        # the rotated view's envelope is wider than 200 units, but the
        # scale is still 1 unit/px
        assert rotated_canvas.mapUnitsPerPixel() == pytest.approx(1.0)

    def test_round_trip_matches_pixel(self, rotated_canvas):
        transform = rotated_canvas.getCoordinateTransform()
        map_point = transform.toMapCoordinatesF(30, 70)
        device = transform.transform(map_point)
        assert device.x() == pytest.approx(30)
        assert device.y() == pytest.approx(70)

    def test_output_is_rotated_not_axis_aligned(
        self, rotated_canvas, polygon_maker_module
    ):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True  # 90x60 map units
        maker = polygon_maker_module.PolygonMaker(rotated_canvas, bin_index)

        features = maker.build_polygons(crs=CRS)

        assert len(features) == 1
        bounds = features[0].geometry().boundingBox()
        angle = math.radians(ROTATION)
        # the envelope of the rotated 90x60 block is wider than the block
        assert bounds.width() == pytest.approx(
            90 * math.cos(angle) + 60 * math.sin(angle)
        )
        assert bounds.height() == pytest.approx(
            90 * math.sin(angle) + 60 * math.cos(angle)
        )


@pytest.mark.usefixtures("qgis_new_project")
class TestBuildPolygons:
    def test_returns_features_without_touching_project(
        self, canvas, polygon_maker_module
    ):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        features = maker.build_polygons(crs=CRS)

        assert len(features) == 1
        assert features[0].geometry().area() == pytest.approx(5400)
        # preview computation must not add layers to the project
        assert len(QgsProject.instance().mapLayers()) == 0

    def test_empty_mask_returns_no_features(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        assert maker.build_polygons(crs=CRS) == []

    def test_rotated_canvas_preserves_area(self, rotated_canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(rotated_canvas, bin_index)

        features = maker.build_polygons(crs=CRS)

        assert len(features) == 1
        assert features[0].geometry().area() == pytest.approx(5400)

    def test_small_regions_are_kept(self, canvas, polygon_maker_module):
        # the mask is flood-filled from the user's clicks, so even a tiny
        # region is a deliberate selection — nothing is dropped by size
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:5, 3:5] = True  # 6 cells

        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)
        features = maker.build_polygons(crs=CRS)

        assert len(features) == 1
        assert features[0].geometry().area() == pytest.approx(600)

    def test_small_holes_are_filled_large_holes_survive(
        self, canvas, polygon_maker_module
    ):
        bin_index = np.zeros((100, 200), dtype=bool)
        bin_index[5:95, 5:95] = True  # 90x90 block at 2 map units/cell
        bin_index[10:13, 10:13] = False  # 9-cell hole -> filled
        bin_index[40:50, 40:50] = False  # 100-cell hole -> kept

        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)
        features = maker.build_polygons(crs=CRS)

        assert len(features) == 1
        # cell = 1x1 map unit here (200 px canvas / 200 cells); the small
        # hole is filled back in, the large one is subtracted
        assert features[0].geometry().area() == pytest.approx(90 * 90 - 100)


@pytest.mark.usefixtures("qgis_new_project")
class TestSimplification:
    def test_staircase_boundary_is_thinned(self, canvas, polygon_maker_module):
        # a pixel staircase (lower-left triangle of cells): the raw
        # dissolved boundary has ~2 vertices per stair step; thinning
        # should collapse it towards the diagonal without losing area
        bin_index = np.zeros((10, 20), dtype=bool)
        for y in range(10):
            bin_index[y, : y + 1] = True  # 1+2+...+10 = 55 cells
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        features = maker.build_polygons(crs=CRS)

        assert len(features) == 1
        geometry = features[0].geometry()
        assert geometry.area() == pytest.approx(5500, rel=0.1)
        # raw staircase ring has ~23 vertices; the thinned ring must be
        # substantially lighter
        assert geometry.constGet().nCoordinates() <= 12


@pytest.mark.usefixtures("qgis_new_project")
class TestAddFeaturesToLayer:
    def test_returns_the_created_layer(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)
        features = maker.build_polygons(crs=CRS)

        layer = polygon_maker_module.add_features_to_layer(features, CRS)

        # the caller can select the created layer (e.g. in the combo box)
        assert layer.id() in QgsProject.instance().mapLayers()
        assert layer.featureCount() == 1

    def test_returns_the_existing_target_layer(self, canvas, polygon_maker_module):
        existing = QgsVectorLayer(f"Polygon?crs={CRS.authid()}", "existing", "memory")
        QgsProject.instance().addMapLayer(existing)

        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)
        features = maker.build_polygons(crs=CRS)

        layer = polygon_maker_module.add_features_to_layer(features, CRS, existing.id())

        assert layer is existing

    def test_each_call_is_one_undo_step(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)
        features = maker.build_polygons(crs=CRS)

        layer = polygon_maker_module.add_features_to_layer(features, CRS)
        polygon_maker_module.add_features_to_layer(features, CRS, layer.id())

        # features go through the edit buffer, one command per call
        assert layer.isEditable()
        assert layer.featureCount() == 2

        layer.undoStack().undo()
        assert layer.featureCount() == 1
        layer.undoStack().undo()
        assert layer.featureCount() == 0

        # redo restores the creations step by step (Ctrl+Shift+Z in QGIS)
        layer.undoStack().redo()
        assert layer.featureCount() == 1
        layer.undoStack().redo()
        assert layer.featureCount() == 2


@pytest.mark.usefixtures("qgis_new_project")
class TestMakePolygons:
    def test_creates_new_layer_with_polygon(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True  # 6x9 = 54 cells
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        maker.make_polygons(crs=CRS)

        layers = list(QgsProject.instance().mapLayers().values())
        assert len(layers) == 1
        layer = layers[0]
        assert layer.name() == "magic_wand"
        features = list(layer.getFeatures())
        assert len(features) == 1
        # 54 cells x (10x10) map units; the rectangle survives
        # simplification exactly (area-based thinning keeps corners)
        assert features[0].geometry().area() == pytest.approx(5400)

    def test_appends_to_existing_layer(self, canvas, polygon_maker_module):
        existing = QgsVectorLayer(f"Polygon?crs={CRS.authid()}", "existing", "memory")
        QgsProject.instance().addMapLayer(existing)

        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        maker.make_polygons(crs=CRS, layer_id=existing.id())

        assert len(QgsProject.instance().mapLayers()) == 1  # no new layer
        assert existing.featureCount() == 1

    def test_deleted_layer_id_falls_back_to_new_layer(
        self, canvas, polygon_maker_module
    ):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        maker.make_polygons(crs=CRS, layer_id="no_such_layer_id")

        layers = list(QgsProject.instance().mapLayers().values())
        assert len(layers) == 1
        assert layers[0].featureCount() == 1

    def test_empty_mask_creates_nothing(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        maker.make_polygons(crs=CRS)

        assert len(QgsProject.instance().mapLayers()) == 0
