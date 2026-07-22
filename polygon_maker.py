import heapq
import math

import numpy as np

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


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labeling of a binary mask.

    Returns (labels, count) where labels holds 1..count per component
    and 0 for background. Works on horizontal runs of True cells with
    union-find (like ImageAnalyzer.flood_fill_components), so the cost
    scales with the number of runs, not the number of cells.
    """
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)

    parent: list[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    rows = []
    prev_starts = prev_ends = prev_ids = None
    for y in range(height):
        diff = np.diff(mask[y].astype(np.int8), prepend=0, append=0)
        starts = np.flatnonzero(diff == 1)
        ends = np.flatnonzero(diff == -1)  # exclusive
        ids = list(range(len(parent), len(parent) + len(starts)))
        parent.extend(ids)
        rows.append((y, starts, ends, ids))

        # merge runs overlapping a run in the previous row (4-connectivity)
        if prev_starts is not None:
            i = j = 0
            while i < len(starts) and j < len(prev_starts):
                if starts[i] < prev_ends[j] and prev_starts[j] < ends[i]:
                    union(ids[i], prev_ids[j])
                if ends[i] < prev_ends[j]:
                    i += 1
                else:
                    j += 1
        prev_starts, prev_ends, prev_ids = starts, ends, ids

    root_to_label: dict[int, int] = {}
    for y, starts, ends, ids in rows:
        for k in range(len(ids)):
            root = find(ids[k])
            label = root_to_label.setdefault(root, len(root_to_label) + 1)
            labels[y, starts[k] : ends[k]] = label
    return labels, len(root_to_label)


# boundary edge directions, clockwise with the region cells on the
# right-hand side (x right, y down): East, South, West, North
EDGE_DIRECTIONS = np.array([(1, 0), (0, 1), (-1, 0), (0, -1)], dtype=np.int64)


def polygonize_mask(mask: np.ndarray, min_cells: int = 0) -> list[list[np.ndarray]]:
    """Trace the boundaries of a binary mask.

    Returns one entry per 4-connected region of True cells: a list of
    rings, exterior first, each a closed (N, 2) float array of ring
    vertices in cell coordinates (x right, y down, cell corners on
    integers). Regions covering fewer than `min_cells` cells are
    skipped before tracing.

    Boundary edges are walked with the region on the right; where two
    regions (or two holes) touch diagonally the walk takes the
    rightmost turn, keeping them separate to match the 4-connectivity
    of the flood fill that produced the mask.
    """
    height, width = mask.shape
    labels, count = label_components(mask)
    if count == 0:
        return []
    if min_cells:
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        mask = (sizes >= min_cells)[labels]
        if not mask.any():
            return []

    padded = np.zeros((height + 2, width + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask
    inner = padded[1:-1, 1:-1]

    # one directed edge per cell side facing background; (dx, dy) is the
    # start-vertex offset from the cell's top-left corner and (bx, by)
    # the offset of the background cell across the edge
    edge_specs = [
        (inner & ~padded[:-2, 1:-1], 0, 0, 0, 0, -1),  # north side, heading East
        (inner & ~padded[1:-1, 2:], 1, 1, 0, 1, 0),  # east side, heading South
        (inner & ~padded[2:, 1:-1], 2, 1, 1, 0, 1),  # south side, heading West
        (inner & ~padded[1:-1, :-2], 3, 0, 1, -1, 0),  # west side, heading North
    ]
    start_x, start_y, direction, owner, across = [], [], [], [], []
    for sides, code, dx, dy, bx, by in edge_specs:
        ys, xs = np.nonzero(sides)
        start_x.append(xs + dx)
        start_y.append(ys + dy)
        direction.append(np.full(len(xs), code, dtype=np.int8))
        owner.append(labels[ys, xs])
        # id of the background cell this edge faces (padded coordinates,
        # so border cells stay in range)
        across.append((ys + by + 1) * (width + 2) + (xs + bx + 1))
    start_x = np.concatenate(start_x)
    start_y = np.concatenate(start_y)
    direction = np.concatenate(direction)
    owner = np.concatenate(owner)
    across = np.concatenate(across)
    edge_count = len(start_x)
    if edge_count == 0:
        return []

    # vertex ids on the (width+1) x (height+1) grid of cell corners
    steps = EDGE_DIRECTIONS[direction]
    end_key = (start_y + steps[:, 1]) * (width + 1) + (start_x + steps[:, 0])
    start_key = start_y * (width + 1) + start_x

    outgoing: dict[int, list[int]] = {}
    for edge in range(edge_count):
        outgoing.setdefault(int(start_key[edge]), []).append(edge)

    visited = np.zeros(edge_count, dtype=bool)
    regions: dict[int, dict[str, list]] = {}
    for first in range(edge_count):
        if visited[first]:
            continue
        vertices = []
        edge = first
        while not visited[edge]:
            visited[edge] = True
            vertices.append((start_x[edge], start_y[edge]))
            candidates = outgoing[int(end_key[edge])]
            if len(candidates) == 1:
                edge = candidates[0]
            else:
                # checkerboard corner: two boundaries pass through this
                # vertex. Where two *regions* touch diagonally, continue
                # along the same component (keeps them separate, matching
                # the 4-connected flood fill); within one component (two
                # holes, or a hole meeting the outside), continue along
                # the same background cell so each ring stays simple
                # instead of merging into a self-touching figure eight.
                same_label = [c for c in candidates if owner[c] == owner[edge]]
                if len(same_label) == 1:
                    edge = same_label[0]
                else:
                    edge = next(c for c in candidates if across[c] == across[edge])

        ring = np.array(vertices, dtype=np.float64)
        # drop collinear vertices (consecutive unit steps merge)
        forward = np.roll(ring, -1, axis=0) - ring
        backward = ring - np.roll(ring, 1, axis=0)
        corner = backward[:, 0] * forward[:, 1] != backward[:, 1] * forward[:, 0]
        ring = ring[corner]
        ring = np.vstack([ring, ring[:1]])

        region = regions.setdefault(int(owner[first]), {"outer": [], "holes": []})
        # traced clockwise (region on the right), exterior rings have
        # positive shoelace area in y-down coordinates, holes negative
        x, y = ring[:, 0], ring[:, 1]
        signed_area = float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1])) / 2
        region["outer" if signed_area > 0 else "holes"].append(ring)

    return [region["outer"] + region["holes"] for region in regions.values()]


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
        # specks below the noise threshold are skipped before tracing
        for rings in polygonize_mask(self.bin_index, min_cells=NOISE_CELLS):
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
