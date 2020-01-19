from qgis.core import QgsProject, QgsRectangle, QgsVectorLayer, QgsFeature, QgsGeometry, QgsCoordinateTransform
import processing
import numpy as np

class PolygonMaker:
    def __init__(self, canvas, bin_index):
        self.bin_index = bin_index
        self.map_canvas = canvas

    def make_vector(self, point, crs, buffer_multiply=1, torel_multiply=3, noise_multiply=10, single_mode=False, layer_id=None):
        #make rectangles by the binary index
        true_points = np.where(self.bin_index)
        func = lambda x, y, size: self.rect_geo(x, y, size)
        np_func = np.frompyfunc(func,3,1)
        size_multiply = self.map_canvas.width() / self.bin_index.shape[1]
        geos = np_func(true_points[1], true_points[0], size_multiply)

        #make layer include all rectangles
        rect_layer = QgsVectorLayer('Polygon?crs=' + crs.authid() + '&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')
        rect_layer_provider = rect_layer.dataProvider()

        for geo in geos:
            rect_feat = QgsFeature()
            rect_feat.setGeometry(geo)
            rect_layer_provider.addFeature(rect_feat)

        #dissolve rectangles layer
        dissolved_layer = processing.run('qgis:dissolve', {'INPUT':rect_layer,'OUTPUT':'memory:'})['OUTPUT']

        #multi part polygon to single part polygon
        single_part_layer = processing.run('qgis:multiparttosingleparts', {'INPUT':dissolved_layer,'OUTPUT':'memory:'})['OUTPUT']
        single_features = single_part_layer.getFeatures()
        
        #fix single part polygon
        output_features = []
        minimum_area = self.rect_geo(0,0, size_multiply).area()
        torelance = self.map_canvas.mapUnitsPerPixel() * torel_multiply * size_multiply
        for feature in single_features:
            if single_mode and not feature.geometry().contains(self.map_canvas.getCoordinateTransform().toMapPoint(point.x(), point.y())):
                continue
            if feature.geometry().area() < minimum_area * noise_multiply:
                continue
            output_geo = feature.geometry().simplify(torelance)
            output_feature = QgsFeature()
            output_feature.setGeometry(output_geo)
            output_features.append(output_feature)
        
        #output layer
        if layer_id:
            output = QgsProject.instance().mapLayer(layer_id)
            if not output:
                output = QgsVectorLayer('Polygon?crs=' + crs.authid() + '&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')
        else:
            output = QgsVectorLayer('Polygon?crs=' + crs.authid() + '&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')

        output_provider = output.dataProvider()
        output_provider.addFeatures(output_features)

        #delete holes of feature
        cleaned_layer = processing.run('qgis:deleteholes', {'INPUT':output, 'MIN_AREA':minimum_area * noise_multiply, 'OUTPUT':'memory:'})['OUTPUT']

        QgsProject.instance().addMapLayer(cleaned_layer)

    #make rectangle geometry by pointXY on Pixels
    def rect_geo(self, x, y, size_multiply):
        point1 = self.map_canvas.getCoordinateTransform().toMapPoint(x * size_multiply, y * size_multiply)
        point2 = self.map_canvas.getCoordinateTransform().toMapPoint((x + 1) * size_multiply, (y + 1) * size_multiply)

        geo = QgsGeometry.fromRect(QgsRectangle(point1.x(), point1.y(), point2.x(), point2.y()))
        return geo
