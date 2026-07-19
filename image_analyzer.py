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
        return true_index

    def get_rgb(self, point):
        pixelColor = self.image.pixelColor(point.x(), point.y())
        red_value = pixelColor.red()
        green_value = pixelColor.green()
        blue_value = pixelColor.blue()
        return (red_value, green_value, blue_value)
