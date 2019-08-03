import numpy as np

class ImageAnalyzer:
    def __init__(self, image):
        self.image = image

    def to_ndarray(self, resize_multiply):
        scaled_img = self.resize(self.image, resize_multiply).convertToFormat(4)

        width = scaled_img.width()
        height = scaled_img.height()

        ptr = scaled_img.constBits()
        ptr.setsize(scaled_img.byteCount())
        arr_rgba = np.array(ptr).reshape(height, width, 4)
        arr_rgb = np.delete(arr_rgba, 3, 2)
        return arr_rgb
        #arr_rgb structure
        #img = x1y1 x2y1 ... xny1
        #      x1y2 x2y2 ... xny2
        #            ...
        #      x1yn x2yn ... xnyn
        #then ndarray is [[x1y1, x2y1 ... xny1],
        #                 [x1y2, x2y2 ... xny2],
        #                 [x1yn, x2yn ... xnyn]]
        #xnyn = [blue, green, red]

    def resize(self, image, resize_multiply):
        scaled_img = image.scaled(image.width() * resize_multiply, image.height() * resize_multiply, True, False)
        return scaled_img

    def to_binary(self, point, resize_multiply=0.2, threshold=50):
        red, green, blue = self.get_rgb(point)
        img_ndarray = self.to_ndarray(resize_multiply)
        abs_ndarray = abs(img_ndarray - [blue, green, red])
        sum_ndarray = abs_ndarray.sum(axis=2)
        max_ndarray = abs_ndarray.max(axis=2)
        true_index = sum_ndarray + max_ndarray*0.5 < threshold
        return true_index

    def get_rgb(self, point):
        pixelColor = self.image.pixelColor(point.x(), point.y())
        red_value = pixelColor.red()
        green_value = pixelColor.green()
        blue_value = pixelColor.blue()
        return (red_value, green_value, blue_value)