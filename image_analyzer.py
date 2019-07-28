import numpy as np

class ImageAnalyzer:
    def __init__(self, image):
        self.image = image

    def to_ndarray(self):
        image = self.image.convertToFormat(4)

        width = image.width()
        height = image.height()

        ptr = image.constBits()
        ptr.setsize(image.byteCount())
        arr = np.array(ptr).reshape(height, width, 4)
        return arr
        #arr structure
        #img = x1y1 x2y1 ... xny1
        #      x1y2 x2y2 ... xny2
        #            ...
        #      x1yn x2yn ... xnyn
        #then ndarray is [[x1y1, x2y1 ... xny1],
        #                 [x1y2, x2y2 ... xny2],
        #                 [x1yn, x2yn ... xnyn]]
        #xnyn = [blue, green, red, alpha]

    def to_binary(self, point, threshold=50):
        red, green, blue = self.get_rgb(point)
        img_ndarray = self.to_ndarray()
        abs_ndarray = abs(img_ndarray - [blue, green, red, 255])
        sum_ndarray = abs_ndarray.sum(axis=2)
        true_index = sum_ndarray < threshold
        return true_index

    def get_rgb(self, point):
        pixelColor = self.image.pixelColor(point.x(), point.y())
        red_value = pixelColor.red()
        green_value = pixelColor.green()
        blue_value = pixelColor.blue()
        return (red_value, green_value, blue_value)