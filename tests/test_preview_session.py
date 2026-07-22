"""Unit tests for the multi-seed feature building (requires QGIS)."""

import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY, QgsRectangle
from qgis.PyQt.QtGui import QColor, QImage

CRS = QgsCoordinateReferenceSystem("EPSG:3857")

WHITE = QColor(255, 255, 255)
RED = QColor(255, 0, 0)
BLUE = QColor(0, 0, 255)


def make_image(width, height, rects):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(WHITE)
    for x, y, w, h, color in rects:
        for py in range(y, y + h):
            for px in range(x, x + w):
                image.setPixelColor(px, py, color)
    return image


@pytest.fixture
def modules(qgis_plugin_path):
    from plugin_dir import image_analyzer, polygon_maker, preview_session

    return image_analyzer, polygon_maker, preview_session


@pytest.mark.usefixtures("native_processing", "qgis_new_project")
class TestBuildMultiSeedFeatures:
    # image pixel (x, y) maps to map point (x, height - y): 1 unit/px
    WIDTH, HEIGHT = 80, 40

    def _setup(self, modules, rects):
        image_analyzer, polygon_maker, preview_session = modules
        image = make_image(self.WIDTH, self.HEIGHT, rects)
        analyzer = image_analyzer.ImageAnalyzer(image)
        grid = polygon_maker.PixelGrid(
            self.WIDTH, self.HEIGHT, QgsRectangle(0, 0, self.WIDTH, self.HEIGHT)
        )
        return preview_session, analyzer, grid

    def test_disjoint_seeds_produce_separate_features(self, modules):
        session_module, analyzer, grid = self._setup(
            modules,
            [(5, 5, 30, 20, RED), (45, 10, 20, 25, BLUE)],
        )

        features = session_module.build_multi_seed_features(
            analyzer,
            grid,
            [QgsPointXY(20, 25), QgsPointXY(55, 15)],  # inside each rect
            50,
            CRS,
        )

        areas = sorted(f.geometry().area() for f in features)
        assert areas == [pytest.approx(20 * 25, rel=0.02), pytest.approx(30 * 20, rel=0.02)]

    def test_seeds_in_the_same_region_do_not_duplicate(self, modules):
        session_module, analyzer, grid = self._setup(modules, [(5, 5, 30, 20, RED)])

        features = session_module.build_multi_seed_features(
            analyzer,
            grid,
            [QgsPointXY(10, 25), QgsPointXY(30, 25)],  # both inside the rect
            50,
            CRS,
        )

        assert len(features) == 1
        assert features[0].geometry().area() == pytest.approx(30 * 20, rel=0.02)

    def test_seed_colors_form_one_combined_model(self, modules):
        # RED | BLUE | RED bands: seeding the left RED and the BLUE band
        # also selects the right RED band (same color as a seed,
        # connected through the other seed's band)
        session_module, analyzer, grid = self._setup(
            modules,
            [(5, 5, 20, 20, RED), (25, 5, 20, 20, BLUE), (45, 5, 20, 20, RED)],
        )

        features = session_module.build_multi_seed_features(
            analyzer,
            grid,
            [QgsPointXY(10, 25), QgsPointXY(35, 25)],
            50,
            CRS,
        )

        assert len(features) == 1
        assert features[0].geometry().area() == pytest.approx(60 * 20, rel=0.02)

    def test_single_seed_matches_the_plain_flow(self, modules):
        session_module, analyzer, grid = self._setup(modules, [(5, 5, 30, 20, RED)])

        features = session_module.build_multi_seed_features(
            analyzer, grid, [QgsPointXY(20, 25)], 50, CRS
        )

        assert len(features) == 1
        assert features[0].geometry().area() == pytest.approx(30 * 20, rel=0.02)

    def test_no_seeds_returns_no_features(self, modules):
        session_module, analyzer, grid = self._setup(modules, [])

        assert (
            session_module.build_multi_seed_features(analyzer, grid, [], 50, CRS) == []
        )
