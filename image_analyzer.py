import numpy as np

from qgis.PyQt.QtGui import QImage


class ImageAnalyzer:
    def __init__(self, image):
        self.image = image

    def to_ndarray(self, resize_multiply):
        scaled_img = self.resize(self.image, resize_multiply).convertToFormat(
            QImage.Format.Format_ARGB32)

        width = scaled_img.width()
        height = scaled_img.height()

        ptr = scaled_img.constBits()
        # QImage.byteCount() was removed in Qt6; sizeInBytes() exists since Qt 5.10
        if hasattr(scaled_img, 'sizeInBytes'):
            ptr.setsize(scaled_img.sizeInBytes())
        else:
            ptr.setsize(scaled_img.byteCount())

        # reshape via bytesPerLine to be robust against scanline padding
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
            height, scaled_img.bytesPerLine() // 4, 4)
        return arr[:, :width, :3]
        #returned structure
        #img = x1y1 x2y1 ... xny1
        #      x1y2 x2y2 ... xny2
        #            ...
        #      x1yn x2yn ... xnyn
        #then ndarray is [[x1y1, x2y1 ... xny1],
        #                 [x1y2, x2y2 ... xny2],
        #                 [x1yn, x2yn ... xnyn]]
        #xnyn = [blue, green, red]

    def resize(self, image, resize_multiply):
        scaled_img = image.scaled(int(image.width() * resize_multiply), int(image.height() * resize_multiply))
        return scaled_img

    def to_binary(self, point, resize_multiply=0.2, threshold=50):
        red, green, blue = self.get_rgb(point)
        img_ndarray = self.to_ndarray(resize_multiply).astype(np.int16)
        abs_ndarray = abs(img_ndarray - [blue, green, red])
        sum_ndarray = abs_ndarray.sum(axis=2)
        max_ndarray = abs_ndarray.max(axis=2)
        true_index = sum_ndarray + max_ndarray * 0.5 < threshold

        # keep only the connected component around the clicked pixel
        seed_x = int(point.x() * true_index.shape[1] / self.image.width())
        seed_y = int(point.y() * true_index.shape[0] / self.image.height())
        return self.flood_fill_component(true_index, seed_x, seed_y)

    def flood_fill_component(self, mask, seed_x, seed_y):
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

        parent = []

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(a, b):
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
                idx = int(np.searchsorted(starts, seed_x, side='right')) - 1
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
                    component[y, starts[k]:ends[k]] = True
        return component

    def find_nearby_seed(self, mask, seed_x, seed_y, radius=3):
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

    def get_rgb(self, point):
        pixelColor = self.image.pixelColor(point.x(), point.y())
        red_value = pixelColor.red()
        green_value = pixelColor.green()
        blue_value = pixelColor.blue()
        return (red_value, green_value, blue_value)
