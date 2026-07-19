"""Unit tests for ImageAnalyzer (binarization and flood fill)."""

from collections import deque

import numpy as np
import pytest
from plugin_dir.image_analyzer import (
    EDGE_TOLERANCE,
    GRADIENT_CAP_RATIO,
    MAX_ANALYSIS_PIXELS,
    ImageAnalyzer,
    bgr_to_lab,
    threshold_to_tolerance,
)
from qgis.PyQt.QtCore import QPoint
from qgis.PyQt.QtGui import QColor, QImage

WHITE = QColor(255, 255, 255)
RED = QColor(255, 0, 0)


def str_mask(rows: list[str]) -> np.ndarray:
    return np.array([[c == "#" for c in row] for row in rows], dtype=bool)


def make_image(
    width: int, height: int, rects: list[tuple[int, int, int, int]]
) -> QImage:
    """White image with red rectangles given as (x, y, w, h)."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(WHITE)
    for x, y, w, h in rects:
        for py in range(y, y + h):
            for px in range(x, x + w):
                image.setPixelColor(px, py, RED)
    return image


class TestToNdarray:
    def test_shape_and_bgr_order(self):
        image = QImage(8, 5, QImage.Format.Format_RGB32)
        image.fill(WHITE)
        image.setPixelColor(3, 2, QColor(10, 20, 30))

        arr = ImageAnalyzer(image).to_ndarray(resize_multiply=1.0)

        assert arr.shape == (5, 8, 3)
        # pixel values are stored as [blue, green, red]
        assert list(arr[2, 3]) == [30, 20, 10]
        assert list(arr[0, 0]) == [255, 255, 255]


class TestGetRgb:
    def test_returns_rgb_of_clicked_pixel(self):
        image = make_image(10, 10, [(2, 2, 3, 3)])
        analyzer = ImageAnalyzer(image)

        assert analyzer.get_rgb(QPoint(3, 3)) == (255, 0, 0)
        assert analyzer.get_rgb(QPoint(0, 0)) == (255, 255, 255)


class TestToBinary:
    def test_click_selects_only_clicked_region(self):
        # two red rectangles; clicking one must not select the other
        image = make_image(60, 40, [(5, 5, 10, 8), (40, 20, 12, 10)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary(QPoint(8, 8), resize_multiply=1.0, threshold=50)

        assert mask.shape == (40, 60)
        assert mask[8, 8]
        assert mask.sum() == 10 * 8  # exactly the clicked rectangle
        assert not mask[25, 45]  # the other rectangle is excluded

    def test_click_on_background_selects_background_component(self):
        image = make_image(30, 20, [(10, 5, 5, 5)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary(QPoint(0, 0), resize_multiply=1.0, threshold=50)

        assert mask[0, 0]
        # background is one connected component surrounding the rectangle
        assert mask.sum() == 30 * 20 - 5 * 5

    def test_resized_binarization(self):
        image = make_image(100, 60, [(20, 12, 40, 24)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary(QPoint(40, 24), resize_multiply=0.5, threshold=50)

        assert mask.shape == (30, 50)
        # scaled rectangle is 20x12 at (10, 6)
        assert mask[12, 20]
        assert abs(int(mask.sum()) - 20 * 12) <= 40  # allow edge wobble

    def test_small_canvas_is_analyzed_at_full_resolution(self):
        image = make_image(60, 40, [(5, 5, 10, 8)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary(QPoint(8, 8))  # resize_multiply omitted

        assert mask.shape == (40, 60)

    def test_huge_canvas_is_downscaled_automatically(self):
        from qgis.PyQt.QtGui import QPainter

        width, height = 3000, 2000  # 6M pixels > MAX_ANALYSIS_PIXELS
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(WHITE)
        painter = QPainter(image)
        painter.fillRect(100, 100, 500, 400, RED)
        painter.end()

        mask = ImageAnalyzer(image).to_binary(QPoint(300, 300))

        scale = (MAX_ANALYSIS_PIXELS / (width * height)) ** 0.5
        assert mask.shape == (int(height * scale), int(width * scale))
        expected_area = (500 * scale) * (400 * scale)
        assert mask.sum() == pytest.approx(expected_area, rel=0.05)


class TestToBinaryMulti:
    def test_single_point_matches_to_binary(self):
        image = make_image(60, 40, [(5, 5, 10, 8), (40, 20, 12, 10)])
        analyzer = ImageAnalyzer(image)

        single = analyzer.to_binary(QPoint(8, 8), resize_multiply=1.0, threshold=50)
        multi = analyzer.to_binary_multi(
            [QPoint(8, 8)], resize_multiply=1.0, threshold=50
        )

        assert (single == multi).all()

    def test_disjoint_seeds_select_the_union(self):
        image = make_image(60, 40, [(5, 5, 10, 8), (40, 20, 12, 10)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary_multi(
            [QPoint(8, 8), QPoint(45, 25)], resize_multiply=1.0, threshold=50
        )

        assert mask[8, 8] and mask[25, 45]
        assert mask.sum() == 10 * 8 + 12 * 10

    def test_region_connected_through_another_seed_color_is_selected(self):
        # three bands A B A'; seeds in A and B. Selecting each seed
        # independently and OR-combining cannot reach A' (same color as
        # A but only connected through B); the combined color model can.
        values = [100] * 10 + [200] * 10 + [100] * 10
        image = gray_image(len(values), 10, values)
        analyzer = ImageAnalyzer(image)

        or_combined = analyzer.to_binary(
            QPoint(5, 5), resize_multiply=1.0, threshold=50
        ) | analyzer.to_binary(QPoint(15, 5), resize_multiply=1.0, threshold=50)
        combined_model = analyzer.to_binary_multi(
            [QPoint(5, 5), QPoint(15, 5)], resize_multiply=1.0, threshold=50
        )

        assert not or_combined[:, 20:].any()  # A' unreachable per seed
        assert combined_model.all()  # A, B and A' all selected

    def test_out_of_bounds_seeds_are_ignored(self):
        image = make_image(30, 20, [(10, 5, 5, 5)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary_multi(
            [QPoint(12, 7), QPoint(500, 500)], resize_multiply=1.0, threshold=50
        )

        assert mask.sum() == 5 * 5

    def test_all_seeds_out_of_bounds_returns_empty(self):
        image = make_image(30, 20, [(10, 5, 5, 5)])
        analyzer = ImageAnalyzer(image)

        mask = analyzer.to_binary_multi(
            [QPoint(-5, -5), QPoint(500, 500)], resize_multiply=1.0, threshold=50
        )

        assert mask.shape == (20, 30)
        assert not mask.any()

    def test_gradients_grow_from_every_seed_component(self):
        # two disjoint smooth gradients separated by a sharp band of a
        # distinct color: gradient growing must run on both components
        threshold = 50
        tolerance = threshold_to_tolerance(threshold)
        gradient = [100 + x for x in range(13)]
        assert tolerance < gray_delta_e(100, 112) < tolerance * GRADIENT_CAP_RATIO
        values = gradient + [220] * 10 + gradient
        image = gray_image(len(values), 10, values)

        mask = ImageAnalyzer(image).to_binary_multi(
            [QPoint(0, 5), QPoint(23, 5)], resize_multiply=1.0, threshold=threshold
        )

        assert mask[:, :13].all()  # first gradient fully grown
        assert mask[:, 23:].all()  # second gradient fully grown
        assert not mask[:, 13:23].any()  # the separating band is excluded


class TestBgrToLab:
    def test_reference_colors(self):
        lab = bgr_to_lab(
            np.array(
                [
                    [255, 255, 255],  # white
                    [0, 0, 0],  # black
                    [0, 0, 255],  # red (BGR order)
                ],
                dtype=np.uint8,
            )
        )
        assert lab[0] == pytest.approx([100.0, 0.0, 0.0], abs=0.5)
        assert lab[1] == pytest.approx([0.0, 0.0, 0.0], abs=0.5)
        assert lab[2] == pytest.approx([53.2, 80.1, 67.2], abs=1.0)


def gray_image(width: int, height: int, column_values: list[int]) -> QImage:
    """Image whose columns are gray levels given per column."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    for x, value in enumerate(column_values):
        color = QColor(value, value, value)
        for y in range(height):
            image.setPixelColor(x, y, color)
    return image


def gray_delta_e(value_a: int, value_b: int) -> float:
    lab = bgr_to_lab(np.array([[value_a] * 3, [value_b] * 3], dtype=np.uint8))
    return float(np.linalg.norm(lab[0] - lab[1]))


class TestGradientGrowing:
    THRESHOLD = 50
    TOLERANCE = threshold_to_tolerance(THRESHOLD)  # ~3.5
    CAP = TOLERANCE * GRADIENT_CAP_RATIO  # ~5.2

    def test_smooth_gradient_is_followed_beyond_tolerance(self):
        # columns 0..12: smooth gray gradient 100 -> 112 (~0.4 dE per step);
        # remaining columns: flat 220 behind a sharp jump
        gradient_width = 13
        values = [100 + x for x in range(gradient_width)] + [220] * 20
        # total gradient span exceeds the plain tolerance but stays under the cap
        assert self.TOLERANCE < gray_delta_e(100, 112) < self.CAP
        image = gray_image(len(values), 10, values)

        mask = ImageAnalyzer(image).to_binary(
            QPoint(5, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )

        assert mask[:, :gradient_width].all()  # whole gradient selected
        assert not mask[:, gradient_width:].any()  # sharp edge stops the growth

    def test_sharp_edge_within_cap_is_not_crossed(self):
        # two flat regions; the second is within the cap but the edge is sharp
        assert self.TOLERANCE < gray_delta_e(100, 112) < self.CAP
        image = gray_image(40, 10, [100] * 20 + [112] * 20)

        mask = ImageAnalyzer(image).to_binary(
            QPoint(5, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )

        assert mask[:, :20].all()
        assert not mask[:, 20:].any()

    def test_ambiguous_threshold_does_not_leak_through_antialiased_edges(self):
        # map-like image: flat regions with 2px anti-aliased ramps between
        # them. At a loose threshold the selection must not chain from
        # region to region through the ramps and flood the whole canvas.
        levels = [80, 130, 180, 230]
        values: list[int] = []
        for i, level in enumerate(levels):
            values += [level] * 18
            if i < len(levels) - 1:
                step = levels[i + 1] - level
                values += [level + step // 3, level + 2 * step // 3]
        image = gray_image(len(values), 10, values)

        loose_threshold = 90  # most ambiguous slider position
        tolerance = threshold_to_tolerance(loose_threshold)
        # regions 3 and 4 are far beyond the tolerance of region 1
        assert gray_delta_e(80, 180) > tolerance
        assert gray_delta_e(80, 230) > tolerance

        mask = ImageAnalyzer(image).to_binary(
            QPoint(5, 5), resize_multiply=1.0, threshold=loose_threshold
        )

        assert mask[5, 5]
        # region 2 may be selected (within tolerance), but 3 and 4 must not be
        region3_start = 2 * 20
        assert not mask[:, region3_start:].any()

    def test_growth_stops_at_cap(self):
        # a long smooth gradient: growth must stop around the cap
        values = list(range(60, 240))
        assert gray_delta_e(60, 239) > self.CAP
        image = gray_image(len(values), 10, values)

        mask = ImageAnalyzer(image).to_binary(
            QPoint(0, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )

        assert mask[5, 0]
        assert not mask[:, -1].any()
        # selected columns form one contiguous band from the left
        selected = np.nonzero(mask[5])[0]
        assert selected.max() == len(selected) - 1


class TestSeedRefinement:
    THRESHOLD = 70
    TOLERANCE = threshold_to_tolerance(THRESHOLD)  # ~6.4

    def _banded_image(self) -> QImage:
        # one visual region made of three shades, next to a distinct
        # background: bands 100 / 110 / 120 (20 columns each), then 230
        values = [100] * 20 + [110] * 20 + [120] * 20 + [230] * 20
        return gray_image(len(values), 10, values)

    def _preconditions(self):
        # neighboring shades are within tolerance, the extreme shades are
        # not: anchoring on the clicked pixel alone cannot select all
        # three bands, re-anchoring on the region median can. The band
        # edges are also too sharp for gradient growing to walk across
        assert gray_delta_e(100, 110) < self.TOLERANCE
        assert gray_delta_e(110, 120) < self.TOLERANCE
        assert gray_delta_e(100, 120) > self.TOLERANCE
        assert gray_delta_e(100, 110) > EDGE_TOLERANCE
        assert gray_delta_e(110, 120) > EDGE_TOLERANCE

    def test_selection_converges_to_the_whole_region(self):
        self._preconditions()
        image = self._banded_image()

        mask = ImageAnalyzer(image).to_binary(
            QPoint(5, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )

        assert mask[:, :60].all()  # all three bands selected
        assert not mask[:, 60:].any()  # background excluded

    def test_selection_is_click_position_independent(self):
        self._preconditions()
        image = self._banded_image()
        analyzer = ImageAnalyzer(image)

        from_left_band = analyzer.to_binary(
            QPoint(5, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )
        from_right_band = analyzer.to_binary(
            QPoint(55, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )

        assert (from_left_band == from_right_band).all()

    def test_seed_patch_median_ignores_outlier_pixel(self):
        # clicking a single outlier pixel inside a flat region behaves as
        # if the surrounding region color was clicked
        image = gray_image(30, 10, [120] * 30)
        image.setPixelColor(15, 5, QColor(230, 230, 230))

        mask = ImageAnalyzer(image).to_binary(
            QPoint(15, 5), resize_multiply=1.0, threshold=self.THRESHOLD
        )

        assert mask.sum() >= 30 * 10 - 1  # whole region (outlier may be excluded)


class TestFloodFillComponent:
    def setup_method(self):
        self.analyzer = ImageAnalyzer(None)

    def test_keeps_only_seed_component(self):
        mask = str_mask(
            [
                "##..##",
                "##..##",
                "......",
                "..##..",
            ]
        )
        out = self.analyzer.flood_fill_component(mask, 0, 0)
        assert (
            out
            == str_mask(
                [
                    "##....",
                    "##....",
                    "......",
                    "......",
                ]
            )
        ).all()

    def test_diagonal_pixels_are_not_connected(self):
        mask = str_mask(
            [
                "#..",
                ".#.",
                "..#",
            ]
        )
        out = self.analyzer.flood_fill_component(mask, 0, 0)
        assert out.sum() == 1
        assert out[0, 0]

    def test_snake_shape_is_fully_connected(self):
        mask = str_mask(
            [
                "#####",
                "....#",
                "#####",
                "#....",
                "#####",
            ]
        )
        out = self.analyzer.flood_fill_component(mask, 4, 4)
        assert (out == mask).all()

    def test_u_shape_branches_merge(self):
        mask = str_mask(
            [
                "#...#",
                "#...#",
                "#####",
            ]
        )
        for seed_x in (0, 4):  # either branch
            out = self.analyzer.flood_fill_component(mask, seed_x, 0)
            assert (out == mask).all()

    def test_seed_on_false_pixel_snaps_to_nearby(self):
        mask = str_mask(
            [
                ".....",
                ".###.",
                ".....",
            ]
        )
        out = self.analyzer.flood_fill_component(mask, 0, 0)
        assert out.sum() == 3

    def test_seed_far_from_component_returns_empty(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[9, 9] = True
        out = self.analyzer.flood_fill_component(mask, 0, 0)
        assert out.sum() == 0

    def test_seed_out_of_bounds_returns_empty(self):
        mask = np.ones((10, 10), dtype=bool)
        out = self.analyzer.flood_fill_component(mask, 99, 99)
        assert out.sum() == 0

    def test_full_mask(self):
        mask = np.ones((20, 30), dtype=bool)
        out = self.analyzer.flood_fill_component(mask, 10, 10)
        assert out.all()

    @pytest.mark.parametrize("trial", range(10))
    def test_matches_bfs_reference(self, trial):
        rng = np.random.default_rng(trial)
        mask = rng.random((30, 40)) < 0.55
        ys, xs = np.nonzero(mask)
        seed_x, seed_y = int(xs[0]), int(ys[0])

        got = self.analyzer.flood_fill_component(mask, seed_x, seed_y)
        expected = self._bfs_reference(mask, seed_x, seed_y)
        assert (got == expected).all()

    @staticmethod
    def _bfs_reference(mask: np.ndarray, seed_x: int, seed_y: int) -> np.ndarray:
        height, width = mask.shape
        out = np.zeros_like(mask)
        queue = deque([(seed_x, seed_y)])
        out[seed_y, seed_x] = True
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if (
                    0 <= nx < width
                    and 0 <= ny < height
                    and mask[ny, nx]
                    and not out[ny, nx]
                ):
                    out[ny, nx] = True
                    queue.append((nx, ny))
        return out


class TestFloodFillComponents:
    def setup_method(self):
        self.analyzer = ImageAnalyzer(None)

    def test_selects_the_components_of_all_seeds(self):
        mask = str_mask(
            [
                "##..##",
                "##..##",
                "......",
                "..##..",
            ]
        )
        out, anchors = self.analyzer.flood_fill_components(mask, [(0, 0), (2, 3)])
        assert (
            out
            == str_mask(
                [
                    "##....",
                    "##....",
                    "......",
                    "..##..",
                ]
            )
        ).all()
        # one anchor per selected component, each inside the output
        assert len(anchors) == 2
        assert all(out[y, x] for x, y in anchors)

    def test_seeds_in_the_same_component_yield_one_anchor(self):
        mask = str_mask(
            [
                "#####",
                ".....",
                "#####",
            ]
        )
        out, anchors = self.analyzer.flood_fill_components(mask, [(0, 0), (4, 0)])
        assert (out == str_mask(["#####", ".....", "....."])).all()
        assert len(anchors) == 1

    def test_seed_on_false_pixel_snaps_to_nearby(self):
        mask = str_mask(
            [
                ".....",
                ".###.",
                ".....",
            ]
        )
        out, anchors = self.analyzer.flood_fill_components(mask, [(0, 0)])
        assert out.sum() == 3
        assert len(anchors) == 1

    def test_unreachable_and_out_of_bounds_seeds_are_ignored(self):
        mask = str_mask(
            [
                "##........",
                "##........",
                "..........",
                ".........#",
            ]
        )
        out, anchors = self.analyzer.flood_fill_components(
            mask, [(0, 0), (5, 2), (99, 99)]
        )
        assert out.sum() == 4  # only the seeded 2x2 block
        assert len(anchors) == 1

    def test_no_valid_seed_returns_empty(self):
        mask = np.zeros((5, 5), dtype=bool)
        mask[4, 4] = True
        out, anchors = self.analyzer.flood_fill_components(mask, [(0, 0)])
        assert not out.any()
        assert anchors == []


class TestFindNearbySeed:
    def setup_method(self):
        self.analyzer = ImageAnalyzer(None)

    def test_finds_nearest_true_pixel(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[5, 6] = True
        mask[8, 8] = True
        assert self.analyzer.find_nearby_seed(mask, 5, 5) == (6, 5)

    def test_returns_none_when_out_of_radius(self):
        mask = np.zeros((10, 10), dtype=bool)
        mask[9, 9] = True
        assert self.analyzer.find_nearby_seed(mask, 0, 0) is None
