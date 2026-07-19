"""Unit tests for PolygonMaker (requires a QGIS environment)."""

import numpy as np
import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

CRS = QgsCoordinateReferenceSystem("EPSG:3857")


@pytest.fixture
def canvas(qgis_app, polygon_maker_module):
    # PixelGrid stands in for the map canvas (a real QgsMapCanvas widget
    # defers resize handling to its event loop, which makes pixel<->map
    # transforms unpredictable in headless tests).
    # 200x100 px grid showing a 200x100 map-unit extent -> 1 unit/px
    return polygon_maker_module.PixelGrid(200, 100, QgsRectangle(0, 0, 200, 100))


@pytest.fixture
def polygon_maker_module(qgis_plugin_path):
    from plugin_dir import polygon_maker

    return polygon_maker


class TestMakeRect:
    def test_single_cell_rect(self, canvas, polygon_maker_module):
        bin_index = np.ones((10, 20), dtype=bool)  # -> 10 px per cell
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        assert maker.size_multiply == pytest.approx(10)
        geo = maker.make_rect(0, 0, maker.size_multiply)
        assert geo.area() == pytest.approx(100)  # 10x10 map units

    def test_run_of_cells_widens_rect(self, canvas, polygon_maker_module):
        bin_index = np.ones((10, 20), dtype=bool)
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        geo = maker.make_rect(0, 0, maker.size_multiply, count=2)
        assert geo.area() == pytest.approx(300)  # 3 cells wide


class TestMakeRects:
    def test_horizontal_runs_are_merged(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[0, 0:3] = True  # one run of 3 cells
        bin_index[2, 5] = True  # isolated cell
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        rects = maker.make_rects()

        assert len(rects) == 2
        assert rects[0].geometry().area() == pytest.approx(300)
        assert rects[1].geometry().area() == pytest.approx(100)

    def test_empty_mask_produces_no_rects(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        assert maker.make_rects() == []


class TestNoiseReduction:
    def test_small_features_are_dropped(self, canvas, polygon_maker_module):
        bin_index = np.ones((10, 20), dtype=bool)
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        from qgis.core import QgsFeature

        small_feature = QgsFeature()
        small_feature.setGeometry(maker.make_rect(0, 0, maker.size_multiply))
        big_feature = QgsFeature()
        big_feature.setGeometry(maker.make_rect(0, 0, maker.size_multiply, count=50))

        output = maker.noise_reduction(
            [small_feature, big_feature], maker.noise_multiply
        )

        assert len(output) == 1
        assert output[0].geometry().area() == pytest.approx(
            big_feature.geometry().area()
        )


@pytest.mark.usefixtures("native_processing", "qgis_new_project")
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


@pytest.mark.usefixtures("native_processing", "qgis_new_project")
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


@pytest.mark.usefixtures("native_processing", "qgis_new_project")
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


@pytest.mark.usefixtures("native_processing", "qgis_new_project")
class TestMakePolygons:
    def test_creates_new_layer_with_polygon(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        bin_index[2:8, 3:12] = True  # 6x9 = 54 cells > noise threshold (40)
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
