import numpy as np

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis import processing

POLYGON_GEOMETRY = Qgis.GeometryType.Polygon

# vertex thinning tolerance, in mask-cell sizes. Simplification is
# area-based (Visvalingam-Whyatt): a pixel staircase is a run of tiny
# triangles of half a cell's area, so a threshold of one cell removes
# them reliably while real corners (much larger triangles) survive —
# unlike distance-based Douglas-Peucker, which clips corners depending
# on where the ring happens to start
SIMPLIFY_TOLERANCE_CELLS = 1.0


def add_features_to_layer(
    features: list[QgsFeature],
    crs: QgsCoordinateReferenceSystem,
    layer_id: str | None = None,
) -> QgsVectorLayer:
    """Append features to the layer with `layer_id`, or to a newly
    created memory layer when no (existing) layer is given."""
    output = None
    if layer_id:
        output = QgsProject.instance().mapLayer(layer_id)
    if output is None:
        output = QgsVectorLayer(f"Polygon?crs={crs.authid()}", "magic_wand", "memory")
        QgsProject.instance().addMapLayer(output)

    output.dataProvider().addFeatures(features)
    output.updateExtents()
    output.triggerRepaint()
    return output


class PolygonMaker:
    def __init__(self, canvas, bin_index: np.ndarray):
        self.bin_index = bin_index
        self.map_canvas = canvas
        self.size_multiply = self.map_canvas.width() / self.bin_index.shape[1]
        self.minimum_area = self.make_rect(0, 0, self.size_multiply).area()
        self.noise_multiply = 40

    def build_polygons(self, crs: QgsCoordinateReferenceSystem) -> list[QgsFeature]:
        """Run the full pipeline and return the resulting features
        without touching the project."""
        rects = self.make_rects()
        if not rects:
            return []
        rects_layer = self.make_layer_by(rects, crs)

        dissolved_layer = processing.run(
            "native:dissolve", {"INPUT": rects_layer, "OUTPUT": "memory:"}
        )["OUTPUT"]
        single_part_layer = processing.run(
            "native:multiparttosingleparts",
            {"INPUT": dissolved_layer, "OUTPUT": "memory:"},
        )["OUTPUT"]
        single_features = single_part_layer.getFeatures()

        denoised_features = self.noise_reduction(single_features, self.noise_multiply)
        if not denoised_features:
            return []
        denoised_layer = self.make_layer_by(denoised_features, crs)

        cell_size = self.minimum_area**0.5
        simplified_layer = processing.run(
            "native:simplifygeometries",
            {
                "INPUT": denoised_layer,
                "METHOD": 2,  # area-based (Visvalingam-Whyatt)
                "TOLERANCE": cell_size * SIMPLIFY_TOLERANCE_CELLS,
                "OUTPUT": "memory:",
            },
        )["OUTPUT"]
        cleaned_layer = processing.run(
            "native:deleteholes",
            {
                "INPUT": simplified_layer,
                # holes and specks share the same area threshold
                "MIN_AREA": self.minimum_area * self.noise_multiply,
                "OUTPUT": "memory:",
            },
        )["OUTPUT"]
        return list(cleaned_layer.getFeatures())

    def make_polygons(
        self, crs: QgsCoordinateReferenceSystem, layer_id: str | None = None
    ) -> None:
        cleaned_features = self.build_polygons(crs)
        if not cleaned_features:
            return
        add_features_to_layer(cleaned_features, crs, layer_id)

    # make rectangle geometry by pointXY on Pixels
    def make_rect(
        self, x: int, y: int, size_multiply: float, count: int = 0
    ) -> QgsGeometry:
        point_top_left = self.map_canvas.getCoordinateTransform().toMapCoordinatesF(
            x * size_multiply, y * size_multiply
        )
        point_bottom_right = self.map_canvas.getCoordinateTransform().toMapCoordinatesF(
            (x + count + 1) * size_multiply, (y + 1) * size_multiply
        )

        return QgsGeometry.fromRect(
            QgsRectangle(
                point_top_left.x(),
                point_top_left.y(),
                point_bottom_right.x(),
                point_bottom_right.y(),
            )
        )

    def make_rects(self) -> list[QgsFeature]:
        # make 2d array including only TRUE pixel index
        # true_points[0]:y axis indexes
        # true_points[1]:x axis indexes
        true_points = np.where(self.bin_index)

        # rectangle making sequence
        geos = []
        # when neighbor pixel also true, incliment this count
        connected_count = 0
        for i in range(len(true_points[0])):
            # skip loops same number to the count
            if connected_count > 0:
                connected_count -= 1
                continue

            x = true_points[1][i]
            y = true_points[0][i]

            # when the final loop
            if i >= len(true_points[0]) - 1:
                geos.append(self.make_rect(x, y, self.size_multiply))
                break

            # calculate connected_count
            while (
                true_points[1][i + connected_count + 1]
                - true_points[1][i + connected_count]
                == 1
            ):
                connected_count += 1
                if i + connected_count + 1 >= len(true_points[0]) - 1:
                    break

            geos.append(self.make_rect(x, y, self.size_multiply, connected_count))

        rects = []
        for geo in geos:
            rect = QgsFeature()
            rect.setGeometry(geo)
            rects.append(rect)
        return rects

    def make_layer_by(
        self, features: list[QgsFeature], crs: QgsCoordinateReferenceSystem
    ) -> QgsVectorLayer:
        features_layer = QgsVectorLayer(
            f"Polygon?crs={crs.authid()}", "magic_wand", "memory"
        )
        features_layer.dataProvider().addFeatures(features)
        features_layer.updateExtents()
        return features_layer

    def noise_reduction(self, features, noise_multiply: float) -> list[QgsFeature]:
        """Drop features smaller than `noise_multiply` mask cells."""
        return [
            feature
            for feature in features
            if feature.geometry().area() >= self.minimum_area * noise_multiply
        ]
