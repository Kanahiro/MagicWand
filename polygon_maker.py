from qgis.core import QgsProject, QgsRectangle, QgsVectorLayer, QgsFeature, QgsGeometry
import processing

class PolygonMaker:
    def __init__(self, canvas, bin_index):
        self.bin_index = bin_index
        self.map_canvas = canvas

    def make_vector(self, point, buffer_dist=0.00005, torelance=0.00003, noise_multiply=10, single_mode=False):
        geos = []
        minimum_area = None

        for y in range(len(self.bin_index)):
            for x in range(len(self.bin_index[y])):
                if not self.bin_index[y][x]:
                    continue

                point1 = self.map_canvas.getCoordinateTransform().toMapPoint(x, y)
                point2 = self.map_canvas.getCoordinateTransform().toMapPoint(x + 1, y + 1)

                new_geo = QgsGeometry.fromRect(QgsRectangle(point1.x(), point1.y(), point2.x(), point2.y()))
                minimum_area = new_geo.area()
                geos.append(new_geo)
        
        unioned_feat = QgsFeature()
        unioned_feat.setGeometry(QgsGeometry().unaryUnion(geos))

        mem_layer = QgsVectorLayer('Polygon?crs=epsg:4326&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')
        mem_layer_provider = mem_layer.dataProvider()
        mem_layer_provider.addFeature(unioned_feat)
        
        single_part_layer = processing.run('qgis:multiparttosingleparts', {'INPUT':mem_layer,'OUTPUT':'memory:'})
        single_features = single_part_layer['OUTPUT'].getFeatures()
        
        output_features = []
        for feature in single_features:
            if single_mode and not feature.geometry().contains(self.map_canvas.getCoordinateTransform().toMapPoint(point.x(), point.y())):
                continue
            if feature.geometry().area() < minimum_area * noise_multiply:
                continue
            output_geo = feature.geometry().buffer(buffer_dist, 1).buffer(-1 * buffer_dist, 1).simplify(torelance)
            output_feature = QgsFeature()
            output_feature.setGeometry(output_geo)
            output_features.append(output_feature)
        
        mem_layer = QgsVectorLayer('Polygon?crs=epsg:4326&field=MYNYM:integer&field=MYTXT:string', 'magic_wand', 'memory')
        mem_layer_provider = mem_layer.dataProvider()
        mem_layer_provider.addFeatures(output_features)
        
        QgsProject.instance().addMapLayer(mem_layer)