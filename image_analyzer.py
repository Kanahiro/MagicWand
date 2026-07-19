import numpy as np

from qgis.PyQt.QtCore import QPoint
from qgis.PyQt.QtGui import QImage

# slider-derived threshold (10-90) -> CIELAB delta-E tolerance.
# Geometric mapping: every slider step scales the tolerance by a constant
# factor, so the strict half of the range stays fine-grained (delta-E
# ~1-3.5, right for flat map colors) while the ambiguous half still
# reaches photo-friendly values
TOLERANCE_MIN = 1.0  # threshold 10 (strictest)
TOLERANCE_MAX = 12.0  # threshold 90 (loosest)


def threshold_to_tolerance(threshold: float) -> float:
    position = min(max((threshold - 10) / 80, 0.0), 1.0)
    return TOLERANCE_MIN * (TOLERANCE_MAX / TOLERANCE_MIN) ** position


# analysis resolution is chosen automatically: full canvas resolution,
# downscaled only when the canvas exceeds this many pixels (e.g. 4K)
MAX_ANALYSIS_PIXELS = 2_000_000
# the initial reference color is the median of a (2r+1)x(2r+1) patch
# around the clicked pixel
SEED_PATCH_RADIUS = 1
# after the first pass the reference color is re-anchored to the median
# color of the selected region, at most this many times. Kept at 1: a
# single re-anchor captures the "unrepresentative click" benefit, while
# further iterations let the reference creep across adjacent regions
REFINE_MAX_ITERATIONS = 1
# ... stopping early once the region changes by less than this ratio
REFINE_CONVERGED_RATIO = 0.02
# the re-anchored reference may drift at most this fraction of the
# tolerance away from the initially clicked color
REFINE_MAX_DRIFT_RATIO = 0.5
# region growing over smooth gradients may reach up to this multiple
# of the tolerance away from the seed color
GRADIENT_CAP_RATIO = 1.5
# adjacent pixels are considered part of the same smooth gradient when
# their delta-E stays below this. True gradients step well below it per
# screen pixel while anti-aliased edges between distinct colors jump far
# above it. Deliberately NOT scaled with the threshold slider: a scaled
# tolerance leaks through anti-aliased boundaries at loose thresholds
# and floods region after region.
EDGE_TOLERANCE = 2.5


def bgr_to_lab(bgr: np.ndarray) -> np.ndarray:
    """Convert a uint8 BGR array (...x3) to CIELAB (sRGB, D65 white point)."""
    rgb = bgr[..., ::-1].astype(np.float64) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = linear @ matrix.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    lightness = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([lightness, a, b], axis=-1)


class ImageAnalyzer:
    def __init__(self, image: QImage):
        self.image = image

    def to_ndarray(self, resize_multiply: float) -> np.ndarray:
        scaled_img = self.resize(self.image, resize_multiply).convertToFormat(
            QImage.Format.Format_ARGB32
        )

        width = scaled_img.width()
        height = scaled_img.height()

        ptr = scaled_img.constBits()
        ptr.setsize(scaled_img.sizeInBytes())

        # reshape via bytesPerLine to be robust against scanline padding;
        # copy() detaches the result from the QImage buffer, which is
        # freed when scaled_img goes out of scope
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
            height, scaled_img.bytesPerLine() // 4, 4
        )
        return arr[:, :width, :3].copy()
        # returned structure
        # img = x1y1 x2y1 ... xny1
        #      x1y2 x2y2 ... xny2
        #            ...
        #      x1yn x2yn ... xnyn
        # then ndarray is [[x1y1, x2y1 ... xny1],
        #                 [x1y2, x2y2 ... xny2],
        #                 [x1yn, x2yn ... xnyn]]
        # xnyn = [blue, green, red]

    def resize(self, image: QImage, resize_multiply: float) -> QImage:
        return image.scaled(
            int(image.width() * resize_multiply), int(image.height() * resize_multiply)
        )

    def to_binary(
        self,
        point: QPoint,
        threshold: float = 50,
        resize_multiply: float | None = None,
    ) -> np.ndarray:
        """Binarize the canvas into "the region the user clicked".

        The reference color starts as the median of a small patch around
        the click (so an unlucky click on an anti-aliased or noisy pixel
        is not taken literally) and is then iteratively re-anchored to
        the median color of the selected region: the selection converges
        to the region's dominant color instead of depending on the exact
        pixel that was clicked.

        Each pass:
        1. compute the perceptual color difference (CIELAB delta-E) of
           every pixel against the reference color
        2. take the connected component around the click where
           delta-E < tolerance
        3. grow the region over smooth gradients: neighboring pixels
           join as long as the step between adjacent pixels is small,
           up to GRADIENT_CAP_RATIO * tolerance from the reference color

        `resize_multiply` is chosen automatically when omitted: full
        resolution, downscaled only for very large canvases.
        """
        return self.to_binary_multi([point], threshold, resize_multiply)

    def to_binary_multi(
        self,
        points: list[QPoint],
        threshold: float = 50,
        resize_multiply: float | None = None,
    ) -> np.ndarray:
        """Binarize the canvas into "the region the user selected" from
        one or more seed points, combined into a single color model
        (see mask_from_bgr_multi). With a single point this is exactly
        to_binary."""
        if resize_multiply is None:
            pixels = self.image.width() * self.image.height()
            resize_multiply = min(1.0, (MAX_ANALYSIS_PIXELS / pixels) ** 0.5)

        tolerance = threshold_to_tolerance(threshold)
        bgr = self.to_ndarray(resize_multiply)

        seeds = [
            (
                int(point.x() * bgr.shape[1] / self.image.width()),
                int(point.y() * bgr.shape[0] / self.image.height()),
            )
            for point in points
        ]
        return self.mask_from_bgr_multi(bgr, seeds, tolerance)

    def mask_from_bgr(
        self, bgr: np.ndarray, seed_x: int, seed_y: int, tolerance: float
    ) -> np.ndarray:
        """Select the region around a seed pixel in a BGR uint8 array.

        The image-independent core of the magic wand, also used by the
        processing algorithm. `tolerance` is a CIELAB delta-E value.
        """
        lab = bgr_to_lab(bgr)
        height, width = lab.shape[:2]
        if not (0 <= seed_x < width and 0 <= seed_y < height):
            return np.zeros((height, width), dtype=bool)

        reference = self.seed_patch_median(lab, seed_x, seed_y)
        region = self.binarize(lab, reference, tolerance, seed_x, seed_y)

        initial_reference = reference
        for _ in range(REFINE_MAX_ITERATIONS):
            if not region.any():
                break
            refined_reference = np.median(lab[region], axis=0)
            drift = float(np.linalg.norm(refined_reference - initial_reference))
            if drift > tolerance * REFINE_MAX_DRIFT_RATIO:
                # the region median is too far from the clicked color;
                # re-anchoring would select something else than clicked
                break
            refined = self.binarize(lab, refined_reference, tolerance, seed_x, seed_y)
            if not self.covers_seed(refined, seed_x, seed_y):
                # the reference drifted away from the click; keep the
                # previous selection
                break
            changed = int(np.count_nonzero(refined != region))
            previous_size = int(np.count_nonzero(region))
            region = refined
            if changed <= previous_size * REFINE_CONVERGED_RATIO:
                break
        return region

    def mask_from_bgr_multi(
        self, bgr: np.ndarray, seeds: list[tuple[int, int]], tolerance: float
    ) -> np.ndarray:
        """Select the region around one or more seed pixels in a BGR
        uint8 array.

        All seed colors form one combined color model: a pixel belongs
        to the core when its delta-E to the *nearest* seed color is
        below the tolerance, and the selection is the union of the
        core's connected components containing a seed (multi-source
        flood fill), grown over smooth gradients like the single-seed
        selection.

        This is a near-superset of OR-combining independent single-seed
        selections: a region matching one seed's color that is only
        connected *through* another seed's color joins the selection too.

        A single seed delegates to mask_from_bgr, including its
        reference re-anchoring; with several seeds the re-anchoring is
        skipped — the seeds themselves anchor the color model.
        """
        height, width = bgr.shape[:2]
        in_bounds = list(
            dict.fromkeys(
                (x, y) for x, y in seeds if 0 <= x < width and 0 <= y < height
            )
        )
        if not in_bounds:
            return np.zeros((height, width), dtype=bool)
        if len(in_bounds) == 1:
            return self.mask_from_bgr(bgr, *in_bounds[0], tolerance)

        lab = bgr_to_lab(bgr)
        delta_e = np.full(lab.shape[:2], np.inf)
        for seed_x, seed_y in in_bounds:
            reference = self.seed_patch_median(lab, seed_x, seed_y)
            np.minimum(delta_e, np.linalg.norm(lab - reference, axis=2), out=delta_e)

        core = delta_e < tolerance
        region, anchors = self.flood_fill_components(core, in_bounds)
        if not region.any():
            return region
        return self.grow_over_gradients(region, lab, delta_e, tolerance, anchors)

    def binarize(
        self,
        lab: np.ndarray,
        reference: np.ndarray,
        tolerance: float,
        seed_x: int,
        seed_y: int,
    ) -> np.ndarray:
        """One selection pass against a fixed reference color."""
        delta_e = np.linalg.norm(lab - reference, axis=2)
        core = delta_e < tolerance
        region = self.flood_fill_component(core, seed_x, seed_y)
        if not region.any():
            return region
        return self.grow_over_gradients(region, lab, delta_e, tolerance)

    def seed_patch_median(
        self, lab: np.ndarray, seed_x: int, seed_y: int, radius: int = SEED_PATCH_RADIUS
    ) -> np.ndarray:
        """Median color of the small patch around the clicked pixel."""
        height, width = lab.shape[:2]
        x0, x1 = max(0, seed_x - radius), min(width, seed_x + radius + 1)
        y0, y1 = max(0, seed_y - radius), min(height, seed_y + radius + 1)
        return np.median(lab[y0:y1, x0:x1].reshape(-1, 3), axis=0)

    def covers_seed(self, mask: np.ndarray, seed_x: int, seed_y: int) -> bool:
        """Whether the mask contains the clicked pixel (or a pixel right
        next to it — the click may sit on an anti-aliased border)."""
        if mask[seed_y, seed_x]:
            return True
        return self.find_nearby_seed(mask, seed_x, seed_y) is not None

    def grow_over_gradients(
        self,
        region: np.ndarray,
        lab: np.ndarray,
        delta_e_seed: np.ndarray,
        tolerance: float,
        anchors: list[tuple[int, int]] | None = None,
    ) -> np.ndarray:
        """Grow `region` over smooth color gradients.

        A neighboring pixel joins the region when the color step from the
        adjacent region pixel is smooth (delta-E < edge tolerance), as long
        as it stays within GRADIENT_CAP_RATIO * tolerance of the seed color.
        Anti-aliased boundaries between distinct colors produce large
        per-pixel steps, so they stop the growth naturally.

        `anchors` names one region pixel per connected component; multi-
        seed regions may have several. By default the region is assumed
        to be a single component.
        """
        edge_tolerance = EDGE_TOLERANCE
        cap = delta_e_seed < tolerance * GRADIENT_CAP_RATIO

        # growth can never leave the connected cap areas around the region
        # (region pixels always lie in the cap), so restrict the iteration
        # to their bounding box
        if anchors is None:
            region_ys, region_xs = np.nonzero(region)
            anchors = [(int(region_xs[0]), int(region_ys[0]))]
        envelope, _ = self.flood_fill_components(cap, anchors)
        env_ys, env_xs = np.nonzero(envelope)
        y0, y1 = env_ys.min(), env_ys.max() + 1
        x0, x1 = env_xs.min(), env_xs.max() + 1

        grown = region[y0:y1, x0:x1].copy()
        env = envelope[y0:y1, x0:x1]
        window = lab[y0:y1, x0:x1]
        smooth_h = (
            np.linalg.norm(window[:, 1:] - window[:, :-1], axis=2) < edge_tolerance
        )
        smooth_v = (
            np.linalg.norm(window[1:, :] - window[:-1, :], axis=2) < edge_tolerance
        )

        while True:
            frontier = np.zeros_like(grown)
            frontier[:, 1:] |= grown[:, :-1] & smooth_h
            frontier[:, :-1] |= grown[:, 1:] & smooth_h
            frontier[1:, :] |= grown[:-1, :] & smooth_v
            frontier[:-1, :] |= grown[1:, :] & smooth_v
            frontier &= env & ~grown
            if not frontier.any():
                break
            grown |= frontier

        result = np.zeros_like(region)
        result[y0:y1, x0:x1] = grown
        return result

    def flood_fill_component(
        self, mask: np.ndarray, seed_x: int, seed_y: int
    ) -> np.ndarray:
        """Extract the 4-connected component of `mask` containing the seed pixel."""
        component, _ = self.flood_fill_components(mask, [(seed_x, seed_y)])
        return component

    def flood_fill_components(
        self, mask: np.ndarray, seeds: list[tuple[int, int]]
    ) -> tuple[np.ndarray, list[tuple[int, int]]]:
        """Union of the 4-connected components of `mask` containing any seed.

        Returns (component_mask, anchors) where `anchors` holds one pixel
        of each selected component, usable as flood seeds elsewhere.
        Seeds outside the mask snap to a nearby True pixel (resizing may
        shift a clicked pixel off the mask); seeds with none nearby are
        ignored.

        Works on horizontal runs of True pixels with union-find, so the cost
        scales with the number of runs, not the number of pixels.
        """
        height, width = mask.shape
        empty = np.zeros_like(mask)

        seeds_by_row: dict[int, list[int]] = {}
        for seed_x, seed_y in seeds:
            if not (0 <= seed_y < height and 0 <= seed_x < width):
                continue
            if not mask[seed_y, seed_x]:
                seed = self.find_nearby_seed(mask, seed_x, seed_y)
                if seed is None:
                    continue
                seed_x, seed_y = seed
            seeds_by_row.setdefault(seed_y, []).append(seed_x)
        if not seeds_by_row:
            return empty, []

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
        seed_runs: list[int] = []
        for y in range(height):
            diff = np.diff(mask[y].astype(np.int8), prepend=0, append=0)
            starts = np.flatnonzero(diff == 1)
            ends = np.flatnonzero(diff == -1)  # exclusive
            ids = list(range(len(parent), len(parent) + len(starts)))
            parent.extend(ids)
            rows.append((y, starts, ends, ids))

            for seed_x in seeds_by_row.get(y, ()):
                idx = int(np.searchsorted(starts, seed_x, side="right")) - 1
                if idx >= 0 and ends[idx] > seed_x:
                    seed_runs.append(ids[idx])

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

        if not seed_runs:
            return empty, []

        seed_roots = {find(run) for run in seed_runs}
        component = empty
        anchors: dict[int, tuple[int, int]] = {}
        for y, starts, ends, ids in rows:
            for k in range(len(ids)):
                root = find(ids[k])
                if root in seed_roots:
                    component[y, starts[k] : ends[k]] = True
                    if root not in anchors:
                        anchors[root] = (int(starts[k]), y)
        return component, list(anchors.values())

    def find_nearby_seed(
        self, mask: np.ndarray, seed_x: int, seed_y: int, radius: int = 3
    ) -> tuple[int, int] | None:
        height, width = mask.shape
        y0 = max(0, seed_y - radius)
        y1 = min(height, seed_y + radius + 1)
        x0 = max(0, seed_x - radius)
        x1 = min(width, seed_x + radius + 1)
        ys, xs = np.nonzero(mask[y0:y1, x0:x1])
        if len(ys) == 0:
            return None
        distances = (ys + y0 - seed_y) ** 2 + (xs + x0 - seed_x) ** 2
        nearest = int(np.argmin(distances))
        return (int(xs[nearest]) + x0, int(ys[nearest]) + y0)

    def get_rgb(self, point: QPoint) -> tuple[int, int, int]:
        pixel_color = self.image.pixelColor(point.x(), point.y())
        return (pixel_color.red(), pixel_color.green(), pixel_color.blue())
