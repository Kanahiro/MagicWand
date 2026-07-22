import heapq
import math

import numpy as np
from osgeo import gdal, ogr

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsMapToPixel,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
)

POLYGON_GEOMETRY = Qgis.GeometryType.Polygon

# vertex thinning tolerance, in mask-cell sizes. Simplification is
# area-based (Visvalingam-Whyatt): a pixel staircase is a run of tiny
# triangles of half a cell's area, so an effective area threshold of one
# square cell removes them reliably while real corners (much larger
# triangles) survive — unlike distance-based Douglas-Peucker, which
# clips corners depending on where the ring happens to start
SIMPLIFY_TOLERANCE_CELLS = 1.0

# features and holes smaller than this many mask cells are noise
NOISE_CELLS = 40


class PixelGrid:
    """Pixel<->map transform context for PolygonMaker.

    Stands in for the map canvas: PolygonMaker only needs the pixel
    width, the map units per pixel, and the pixel->map transform, so
    any georeferenced pixel grid (e.g. a raster) works as an input.
    Assumes square pixels.
    """

    def __init__(
        self, width: int, height: int, extent: QgsRectangle, rotation: float = 0.0
    ):
        # `extent` is the axis-aligned envelope of the (possibly rotated)
        # visible area, as QgsMapCanvas.visibleExtent() reports it: for a
        # rotated view its width spans the rotated pixel grid's corners,
        # not `width` pixels
        self._width = width
        angle = math.radians(rotation)
        self._map_units_per_pixel = extent.width() / (
            width * abs(math.cos(angle)) + height * abs(math.sin(angle))
        )
        self._transform = QgsMapToPixel(
            self._map_units_per_pixel,
            extent.center().x(),
            extent.center().y(),
            width,
            height,
            rotation,
        )

    def width(self) -> int:
        return self._width

    def mapUnitsPerPixel(self) -> float:
        return self._map_units_per_pixel

    def getCoordinateTransform(self) -> QgsMapToPixel:
        return self._transform


def add_features_to_layer(
    features: list[QgsFeature],
    crs: QgsCoordinateReferenceSystem,
    layer_id: str | None = None,
) -> QgsVectorLayer:
    """Append features to the layer with `layer_id`, or to a newly
    created memory layer when no (existing) layer is given.

    Features are added through the layer's edit buffer as a single edit
    command, so each call can be undone with Ctrl+Z (the edits stay
    uncommitted until the user saves the layer)."""
    output = None
    if layer_id:
        output = QgsProject.instance().mapLayer(layer_id)
    if output is None:
        output = QgsVectorLayer(f"Polygon?crs={crs.authid()}", "magic_wand", "memory")
        QgsProject.instance().addMapLayer(output)

    if output.isEditable() or output.startEditing():
        output.beginEditCommand("Magic Wand: add polygon")
        output.addFeatures(features)
        output.endEditCommand()
    else:
        # layer cannot enter an edit session (e.g. read-only source);
        # fall back to a direct provider write without undo support
        output.dataProvider().addFeatures(features)

    output.updateExtents()
    output.triggerRepaint()
    return output


def polygonize_mask(mask: np.ndarray) -> list[list[np.ndarray]]:
    """Trace the boundaries of a binary mask (GDAL polygonize).

    Returns one entry per 4-connected region of True cells: a list of
    rings, exterior first, each a closed (N, 2) float array of ring
    vertices in cell coordinates (x right, y down, cell corners on
    integers).
    """
    height, width = mask.shape
    raster = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_Byte)
    # identity geotransform: polygon coordinates are cell corners
    raster.SetGeoTransform((0, 1, 0, 0, 0, 1))
    band = raster.GetRasterBand(1)
    band.WriteArray(mask.astype(np.uint8))

    vector = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = vector.CreateLayer("mask", None, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("value", ogr.OFTInteger))
    # the band doubles as its own mask, so False cells produce no
    # feature at all; 4-connectivity (the default) matches the
    # 4-connected flood fill that produced the mask
    gdal.Polygonize(band, band, layer, 0)

    polygons = []
    for feature in layer:
        geometry = feature.GetGeometryRef()
        rings = [
            np.array(geometry.GetGeometryRef(i).GetPoints(), dtype=np.float64)[:, :2]
            for i in range(geometry.GetGeometryCount())
        ]
        polygons.append(rings)
    return polygons


def ring_area(ring: np.ndarray) -> float:
    """Unsigned shoelace area of a closed (N, 2) ring."""
    x, y = ring[:, 0], ring[:, 1]
    return abs(float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))) / 2


def simplify_ring(ring: np.ndarray, min_triangle_area: float) -> np.ndarray:
    """Thin a closed ring with Visvalingam-Whyatt simplification.

    Repeatedly removes the vertex spanning the smallest triangle with
    its neighbors while that area is below `min_triangle_area`, never
    reducing the ring below a triangle.
    """
    points = ring[:-1]  # drop the closing vertex, treat as circular
    n = len(points)
    if n <= 3:
        return ring

    prev = np.roll(np.arange(n), 1)
    next_ = np.roll(np.arange(n), -1)
    alive = np.ones(n, dtype=bool)
    alive_count = n

    def triangle_area(i: int) -> float:
        a, b, c = points[prev[i]], points[i], points[next_[i]]
        return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2

    heap = [(triangle_area(i), i) for i in range(n)]
    heapq.heapify(heap)

    while heap and alive_count > 3:
        area, i = heapq.heappop(heap)
        if not alive[i]:
            continue
        if area != triangle_area(i):
            # stale entry: neighbors changed since it was pushed
            heapq.heappush(heap, (triangle_area(i), i))
            continue
        if area >= min_triangle_area:
            break
        alive[i] = False
        alive_count -= 1
        next_[prev[i]] = next_[i]
        prev[next_[i]] = prev[i]
        for j in (prev[i], next_[i]):
            heapq.heappush(heap, (triangle_area(j), j))

    kept = points[alive]
    return np.vstack([kept, kept[:1]])


class PolygonMaker:
    def __init__(self, canvas, bin_index: np.ndarray):
        self.bin_index = bin_index
        self.map_canvas = canvas
        self.size_multiply = self.map_canvas.width() / self.bin_index.shape[1]

    def build_polygons(self, crs: QgsCoordinateReferenceSystem) -> list[QgsFeature]:
        """Polygonize the mask and return the resulting features without
        touching the project.

        The whole pipeline — boundary tracing, noise and hole removal,
        vertex thinning — runs in mask-cell coordinates; only the final
        vertices are transformed to map coordinates, so any pixel->map
        transform (including a rotated canvas) applies uniformly.
        """
        features = []
        for rings in polygonize_mask(self.bin_index):
            if ring_area(rings[0]) < NOISE_CELLS:
                continue  # speck
            kept_rings = [
                simplify_ring(ring, SIMPLIFY_TOLERANCE_CELLS**2)
                for ring in rings
                # holes and specks share the same area threshold
                if ring is rings[0] or ring_area(ring) >= NOISE_CELLS
            ]
            feature = QgsFeature()
            feature.setGeometry(
                QgsGeometry.fromPolygonXY(
                    [self.ring_to_map(ring) for ring in kept_rings]
                )
            )
            features.append(feature)
        return features

    def ring_to_map(self, ring: np.ndarray) -> list[QgsPointXY]:
        """Transform a ring from cell coordinates to map coordinates."""
        to_map = self.map_canvas.getCoordinateTransform().toMapCoordinatesF
        return [to_map(x * self.size_multiply, y * self.size_multiply) for x, y in ring]

    def make_polygons(
        self, crs: QgsCoordinateReferenceSystem, layer_id: str | None = None
    ) -> None:
        cleaned_features = self.build_polygons(crs)
        if not cleaned_features:
            return
        add_features_to_layer(cleaned_features, crs, layer_id)
