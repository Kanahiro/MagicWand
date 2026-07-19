"""End-to-end tests for the magicwand:polygonizebyseeds processing algorithm."""

import numpy as np
import pytest
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)

WHITE = (255, 255, 255)
RED = (255, 0, 0)
BLUE = (0, 0, 255)


@pytest.fixture(scope="session")
def magicwand_provider(qgis_plugin_path, native_processing):
    from plugin_dir.processing_provider.provider import MagicWandProvider

    provider = MagicWandProvider()
    QgsApplication.processingRegistry().addProvider(provider)
    return provider


def write_rgb_geotiff(path, width, height, rects, bands=3):
    """White GeoTIFF with colored rectangles given as (x, y, w, h, color),
    georeferenced at 1 map unit per pixel, EPSG:3857, top-left (0, height)."""
    from osgeo import gdal, osr

    rgb = np.full((height, width, 3), 255, dtype=np.uint8)
    for x, y, w, h, color in rects:
        rgb[y : y + h, x : x + w] = color

    dataset = gdal.GetDriverByName("GTiff").Create(
        str(path), width, height, bands, gdal.GDT_Byte
    )
    dataset.SetGeoTransform([0, 1, 0, height, 0, -1])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    dataset.SetProjection(srs.ExportToWkt())
    for band in range(bands):
        dataset.GetRasterBand(band + 1).WriteArray(rgb[:, :, band % 3])
    dataset = None
    return str(path)


def seed_layer(points):
    layer = QgsVectorLayer("Point?crs=EPSG:3857", "seeds", "memory")
    features = []
    for x, y in points:
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    return layer


@pytest.mark.usefixtures("magicwand_provider", "qgis_new_project")
class TestPolygonizeBySeeds:
    def test_one_polygon_per_seed(self, tmp_path):
        from qgis import processing

        # two colored rectangles on white; pixel row y=5..25 -> map y=15..35
        raster = write_rgb_geotiff(
            tmp_path / "map.tif",
            80,
            40,
            [(5, 5, 30, 20, RED), (45, 10, 20, 25, BLUE)],
        )
        seeds = seed_layer([(20, 25), (55, 15)])  # inside each rectangle

        result = processing.run(
            "magicwand:polygonizebyseeds",
            {
                "INPUT": raster,
                "SEEDS": seeds,
                "TOLERANCE": 3.5,
                "OUTPUT": "memory:",
            },
        )

        output = result["OUTPUT"]
        features = {f["seed_id"]: f for f in output.getFeatures()}
        assert len(features) == 2
        assert features[1].geometry().area() == pytest.approx(30 * 20)
        assert features[2].geometry().area() == pytest.approx(20 * 25)
        # each polygon contains its own seed
        assert (
            features[1].geometry().contains(QgsGeometry.fromPointXY(QgsPointXY(20, 25)))
        )
        assert (
            features[2].geometry().contains(QgsGeometry.fromPointXY(QgsPointXY(55, 15)))
        )

    def test_seed_outside_raster_is_skipped(self, tmp_path):
        from qgis import processing

        raster = write_rgb_geotiff(tmp_path / "map.tif", 60, 40, [(5, 5, 30, 20, RED)])
        seeds = seed_layer([(1000, 1000)])

        result = processing.run(
            "magicwand:polygonizebyseeds",
            {
                "INPUT": raster,
                "SEEDS": seeds,
                "TOLERANCE": 3.5,
                "OUTPUT": "memory:",
            },
        )

        assert result["OUTPUT"].featureCount() == 0

    def test_rejects_non_rgb_raster(self, tmp_path):
        from qgis import processing
        from qgis.core import QgsProcessingException

        raster = write_rgb_geotiff(tmp_path / "single_band.tif", 60, 40, [], bands=1)
        seeds = seed_layer([(30, 20)])

        with pytest.raises(QgsProcessingException):
            processing.run(
                "magicwand:polygonizebyseeds",
                {
                    "INPUT": raster,
                    "SEEDS": seeds,
                    "TOLERANCE": 3.5,
                    "OUTPUT": "memory:",
                },
            )
