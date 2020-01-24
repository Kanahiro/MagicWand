from qgis.core import QgsProject, QgsRectangle, QgsVectorLayer, QgsFeature, QgsGeometry, QgsCoordinateTransform
import processing
import numpy as np

class PolygonMaker:
    def __init__(self, canvas, bin_index):
        self.bin_index = bin_index
        self.map_canvas = canvas
        self.size_multiply = self.map_canvas.width() / self.bin_index.shape[1]
        self.minimum_area = self.make_rect(0,0, self.size_multiply).area()
        self.noise_multiply = 40

    def make_polygons(self, point, crs, single_mode=False, layer_id=None):
        rects = self.make_rects()
        rects_layer = self.make_layer_by(rects, crs)

        dissolved_layer = processing.run('qgis:dissolve', {'INPUT':rects_layer,'OUTPUT':'memory:'})['OUTPUT']
        single_part_layer = processing.run('qgis:multiparttosingleparts', {'INPUT':dissolved_layer,'OUTPUT':'memory:'})['OUTPUT']
        single_features = single_part_layer.getFeatures()
        
        if single_mode:
            for feature in single_features:
                if feature.geometry().contains(self.map_canvas.getCoordinateTransform().toMapPoint(point.x(), point.y())):
                    single_features = [feature]
                    break
        
        denoised_features = self.noise_reduction(single_features, self.noise_multiply)
        denoised_layer = self.make_layer_by(denoised_features, crs)
        cleaned_layer = processing.run('qgis:deleteholes', {'INPUT':denoised_layer, 'MIN_AREA':self.minimum_area * self.size_multiply * self.noise_multiply, 'OUTPUT':'memory:'})['OUTPUT']
        cleaned_features = cleaned_layer.getFeatures()
        
        #output layer
        output = QgsVectorLayer('Polygon?crs=' + crs.authid() + '&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')
        if layer_id:
            output = QgsProject.instance().mapLayer(layer_id)

        output_provider = output.dataProvider()
        output_provider.addFeatures(cleaned_features)

        QgsProject.instance().addMapLayer(output)

    #make rectangle geometry by pointXY on Pixels
    def make_rect(self, x, y, size_multiply, count=0):
        pointTopLeft = self.map_canvas.getCoordinateTransform().toMapPoint(x * size_multiply, y * size_multiply)
        pointBottomRight = self.map_canvas.getCoordinateTransform().toMapPoint((x + count + 1) * size_multiply, (y + 1) * size_multiply)

        geo = QgsGeometry.fromRect(QgsRectangle(pointTopLeft.x(), pointTopLeft.y(), pointBottomRight.x(), pointBottomRight.y()))
        return geo

    def make_rects(self):
        #make 2d array including only TRUE pixel index
        #true_points[0]:y axis indexes
        #true_points[1]:x axis indexes
        true_points = np.where(self.bin_index)

        #rectangle making sequence
        geos = []
        #when neighbor pixel also true, incliment this count
        connectedCount = 0
        for i in range(len(true_points[0])):
            #skip loops same number to the count
            if connectedCount > 0:
                connectedCount = connectedCount - 1
                continue

            x = true_points[1][i]
            y = true_points[0][i]

            #when the final loop
            if i >= len(true_points[0]) - 1:
                geos.append(self.make_rect(x, y, self.size_multiply))
                break

            #calculate connectedCount
            while true_points[1][i + connectedCount + 1] - true_points[1][i + connectedCount] == 1:
                connectedCount = connectedCount + 1
                if i + connectedCount + 1 >= len(true_points[0]) - 1:
                    break

            geos.append(self.make_rect(x, y, self.size_multiply, connectedCount))

        rects = []
        for geo in geos:
            rect = QgsFeature()
            rect.setGeometry(geo)
            rects.append(rect)
        return rects

    def make_layer_by(self, features, crs):
        features_layer = QgsVectorLayer('Polygon?crs=' + crs.authid() + '&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')
        features_layer_provider = features_layer.dataProvider()
        features_layer_provider.addFeatures(features)
        return features_layer

    def noise_reduction(self, features, noise_multiply, torel_multiply=3):
        output = []
        torelance = self.map_canvas.mapUnitsPerPixel() * torel_multiply * self.size_multiply ** 0.6
        for feature in features:
            if feature.geometry().area() < self.minimum_area * noise_multiply:
                continue
            output_geo = feature.geometry().simplify(torelance)
            output_feature = QgsFeature()
            output_feature.setGeometry(output_geo)
            output.append(output_feature)

        return output