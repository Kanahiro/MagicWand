"""Unit tests for PolygonMaker (requires a QGIS environment)."""

import numpy as np
import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsMapToPixel,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

CRS = QgsCoordinateReferenceSystem("EPSG:3857")


class FakeCanvas:
    """Deterministic stand-in for the parts of QgsMapCanvas PolygonMaker uses.

    A real QgsMapCanvas widget defers resize handling to its event loop,
    which makes pixel<->map transforms unpredictable in headless tests.
    """

    def __init__(self, width: int, height: int, extent: QgsRectangle):
        self._width = width
        self._mupp = extent.width() / width
        self._transform = QgsMapToPixel(
            self._mupp,
            extent.center().x(),
            extent.center().y(),
            width,
            height,
            0,
        )

    def width(self) -> int:
        return self._width

    def mapUnitsPerPixel(self) -> float:
        return self._mupp

    def getCoordinateTransform(self) -> QgsMapToPixel:
        return self._transform


@pytest.fixture
def canvas(qgis_app):
    # 200x100 px canvas showing a 200x100 map-unit extent -> 1 unit/px
    return FakeCanvas(200, 100, QgsRectangle(0, 0, 200, 100))


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
        assert features[0].geometry().area() == pytest.approx(5400, rel=0.15)
        # preview computation must not add layers to the project
        assert len(QgsProject.instance().mapLayers()) == 0

    def test_empty_mask_returns_no_features(self, canvas, polygon_maker_module):
        bin_index = np.zeros((10, 20), dtype=bool)
        maker = polygon_maker_module.PolygonMaker(canvas, bin_index)

        assert maker.build_polygons(crs=CRS) == []


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
        # 54 cells x (10x10) map units; simplify may shave corners a little
        assert features[0].geometry().area() == pytest.approx(5400, rel=0.15)

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
