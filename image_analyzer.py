import numpy as np

from qgis.PyQt.QtCore import QPoint
from qgis.PyQt.QtGui import QImage

# slider threshold (10-90) -> CIELAB delta-E tolerance (3-27)
DELTA_E_PER_THRESHOLD = 0.3
# analysis resolution is chosen automatically: full canvas resolution,
# downscaled only when the canvas exceeds this many pixels (e.g. 4K)
MAX_ANALYSIS_PIXELS = 2_000_000
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

        1. compute the perceptual color difference (CIELAB delta-E) of
           every pixel against the clicked color
        2. take the connected component around the click where
           delta-E < tolerance
        3. grow the region over smooth gradients: neighboring pixels
           join as long as the step between adjacent pixels is small,
           up to GRADIENT_CAP_RATIO * tolerance from the seed color

        `resize_multiply` is chosen automatically when omitted: full
        resolution, downscaled only for very large canvases.
        """
        if resize_multiply is None:
            pixels = self.image.width() * self.image.height()
            resize_multiply = min(1.0, (MAX_ANALYSIS_PIXELS / pixels) ** 0.5)

        tolerance = threshold * DELTA_E_PER_THRESHOLD
        lab = bgr_to_lab(self.to_ndarray(resize_multiply))

        red, green, blue = self.get_rgb(point)
        seed_lab = bgr_to_lab(np.array([[blue, green, red]], dtype=np.uint8))[0]
        delta_e_seed = np.linalg.norm(lab - seed_lab, axis=2)

        seed_x = int(point.x() * lab.shape[1] / self.image.width())
        seed_y = int(point.y() * lab.shape[0] / self.image.height())

        core = delta_e_seed < tolerance
        region = self.flood_fill_component(core, seed_x, seed_y)
        if not region.any():
            return region
        return self.grow_over_gradients(region, lab, delta_e_seed, tolerance)

    def grow_over_gradients(
        self,
        region: np.ndarray,
        lab: np.ndarray,
        delta_e_seed: np.ndarray,
        tolerance: float,
    ) -> np.ndarray:
        """Grow `region` over smooth color gradients.

        A neighboring pixel joins the region when the color step from the
        adjacent region pixel is smooth (delta-E < edge tolerance), as long
        as it stays within GRADIENT_CAP_RATIO * tolerance of the seed color.
        Anti-aliased boundaries between distinct colors produce large
        per-pixel steps, so they stop the growth naturally.
        """
        edge_tolerance = EDGE_TOLERANCE
        cap = delta_e_seed < tolerance * GRADIENT_CAP_RATIO

        # growth can never leave the connected cap area around the region,
        # so restrict the iteration to its bounding box
        region_ys, region_xs = np.nonzero(region)
        envelope = self.flood_fill_component(cap, int(region_xs[0]), int(region_ys[0]))
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
        """Extract the 4-connected component of `mask` containing the seed pixel.

        Works on horizontal runs of True pixels with union-find, so the cost
        scales with the number of runs, not the number of pixels.
        """
        height, width = mask.shape
        empty = np.zeros_like(mask)
        if not (0 <= seed_y < height and 0 <= seed_x < width):
            return empty
        if not mask[seed_y, seed_x]:
            # resizing may shift the clicked pixel off the mask; look nearby
            seed = self.find_nearby_seed(mask, seed_x, seed_y)
            if seed is None:
                return empty
            seed_x, seed_y = seed

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
        seed_run = -1
        for y in range(height):
            diff = np.diff(mask[y].astype(np.int8), prepend=0, append=0)
            starts = np.flatnonzero(diff == 1)
            ends = np.flatnonzero(diff == -1)  # exclusive
            ids = list(range(len(parent), len(parent) + len(starts)))
            parent.extend(ids)
            rows.append((y, starts, ends, ids))

            if y == seed_y:
                idx = int(np.searchsorted(starts, seed_x, side="right")) - 1
                if idx >= 0 and ends[idx] > seed_x:
                    seed_run = ids[idx]

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

        if seed_run < 0:
            return empty

        seed_root = find(seed_run)
        component = empty
        for y, starts, ends, ids in rows:
            for k in range(len(ids)):
                if find(ids[k]) == seed_root:
                    component[y, starts[k] : ends[k]] = True
        return component

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
