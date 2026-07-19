import numpy as np

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
)

from ..image_analyzer import ImageAnalyzer
from ..polygon_maker import PixelGrid, PolygonMaker

DEFAULT_TOLERANCE = 3.5


def _seed_id_field() -> QgsField:
    try:
        # QMetaType-based constructor, available since QGIS 3.38 and the
        # only one left in QGIS 4.x
        from qgis.PyQt.QtCore import QMetaType

        return QgsField("seed_id", QMetaType.Type.Int)
    except TypeError:
        from qgis.PyQt.QtCore import QVariant

        return QgsField("seed_id", QVariant.Int)


class PolygonizeBySeedsAlgorithm(QgsProcessingAlgorithm):
    """Magic-wand polygonization as a processing algorithm.

    One seed feature = one magic-wand selection = one output feature:
    every point of a (multi)point seed feature contributes to the same
    selection — the seed colors form one combined color model and the
    flood fill grows from all points at once — exactly like the
    interactive tool's Add Point button. Pair it with the built-in
    "Convert map to raster" algorithm to reproduce the interactive
    behavior in models and batch runs.
    """

    INPUT = "INPUT"
    SEEDS = "SEEDS"
    TOLERANCE = "TOLERANCE"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "polygonizebyseeds"

    def displayName(self) -> str:
        return "Polygonize by seed points"

    def shortHelpString(self) -> str:
        return (
            "For each seed feature, traces the connected regions of "
            "similar color in an RGB raster (magic wand selection: "
            "perceptual CIELAB delta-E, flood fill, gradient growing) "
            "and outputs one multipolygon feature tagged with the seed's "
            "id.\n\n"
            "One seed feature is one selection: all points of a "
            "multipoint feature feed one combined color model — a pixel "
            "matches when it is close to the nearest of the seed colors "
            "and connected to any of the points — like the Add Point "
            "button of the interactive tool. Use one single-point "
            "feature per region to get one polygon per point.\n\n"
            "The input must be an 8-bit raster with at least 3 bands "
            "(R, G, B). To run it against styled map layers, render them "
            "first with the built-in 'Convert map to raster' algorithm.\n\n"
            "The color tolerance is a CIELAB delta-E value; the "
            "interactive tool's Color Threshold slider covers roughly "
            "1 (strict) to 12 (ambiguous)."
        )

    def createInstance(self) -> "PolygonizeBySeedsAlgorithm":
        return PolygonizeBySeedsAlgorithm()

    def initAlgorithm(self, config=None) -> None:
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                "Input RGB raster (e.g. from 'Convert map to raster')",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.SEEDS,
                "Seed points (one selection per feature)",
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TOLERANCE,
                "Color tolerance (CIELAB delta-E)",
                QgsProcessingParameterNumber.Type.Double,
                defaultValue=DEFAULT_TOLERANCE,
                minValue=0.1,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                "Polygons",
                QgsProcessing.TypeVectorPolygon,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        raster = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        seeds = self.parameterAsSource(parameters, self.SEEDS, context)
        tolerance = self.parameterAsDouble(parameters, self.TOLERANCE, context)

        provider = raster.dataProvider()
        if raster.bandCount() < 3:
            raise QgsProcessingException(
                "The input raster must have at least 3 bands (R, G, B). "
                "Render styled layers with 'Convert map to raster' first."
            )
        if provider.dataType(1) != Qgis.DataType.Byte:
            raise QgsProcessingException(
                "The input raster must be 8-bit (Byte). Render styled "
                "layers with 'Convert map to raster' first."
            )

        width, height = raster.width(), raster.height()
        extent = raster.extent()
        x_res = extent.width() / width
        y_res = extent.height() / height
        if abs(x_res - y_res) > 0.01 * x_res:
            feedback.pushWarning(
                "The raster pixels are not square; geometry may be "
                f"slightly distorted (x: {x_res:.6g}, y: {y_res:.6g})"
            )

        def band_array(band: int) -> np.ndarray:
            block = provider.block(band, extent, width, height)
            return np.frombuffer(bytes(block.data()), dtype=np.uint8).reshape(
                height, width
            )

        bgr = np.dstack([band_array(3), band_array(2), band_array(1)])

        fields = QgsFields()
        fields.append(_seed_id_field())
        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            Qgis.WkbType.MultiPolygon,
            raster.crs(),
        )

        grid = PixelGrid(width, height, extent)
        to_pixel = grid.getCoordinateTransform()
        analyzer = ImageAnalyzer(None)

        request = QgsFeatureRequest().setDestinationCrs(
            raster.crs(), context.transformContext()
        )
        total = seeds.featureCount() or 1
        for i, seed in enumerate(seeds.getFeatures(request)):
            if feedback.isCanceled():
                break

            geometry = seed.geometry()
            points = (
                geometry.asMultiPoint()
                if geometry.isMultipart()
                else [geometry.asPoint()]
            )

            # one selection per seed feature: all its points feed one
            # combined color model and the flood fill grows from all of
            # them at once, like the interactive tool's Add Point button
            pixel_seeds = []
            for point in points:
                device = to_pixel.transform(point)
                pixel_seeds.append((int(device.x()), int(device.y())))
            mask = analyzer.mask_from_bgr_multi(bgr, pixel_seeds, tolerance)

            if not mask.any():
                feedback.pushInfo(f"Seed {seed.id()}: no region found, skipped")
            else:
                parts = PolygonMaker(grid, mask).build_polygons(crs=raster.crs())
                if parts:
                    out = QgsFeature(fields)
                    out.setGeometry(
                        QgsGeometry.collectGeometry([part.geometry() for part in parts])
                    )
                    out["seed_id"] = seed.id()
                    sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

            feedback.setProgress(int(100 * (i + 1) / total))

        return {self.OUTPUT: dest_id}
