"""Unit tests for ImageAnalyzer (binarization and flood fill)."""

from collections import deque

import numpy as np
import pytest
from plugin_dir.image_analyzer import ImageAnalyzer
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
