# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt, QSize, QLocale
from qgis.PyQt.QtGui import QIcon, QImage, QPainter
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsProject, QgsMapLayer, QgsRectangle, QgsPoint, QgsMultiBandColorRenderer, QgsRaster, QgsMapSettings, QgsMapRendererCustomPainterJob, QgsSettings
# Initialize Qt resources from file resources.py
from .resources import *

# Import the code for the DockWidget
from .magic_wand_dockwidget import MagicwandDockWidget
import os.path

from .Utils import ClickTool
from .image_analyzer import ImageAnalyzer
from .polygon_maker import PolygonMaker


class Magicwand:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface

        self.canvas = iface.mapCanvas()

        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)

        # initialize locale
        locale = QgsSettings().value('locale/userLocale', QLocale().name())[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'Magicwand_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Magic Wand')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'Magicwand')
        self.toolbar.setObjectName(u'Magicwand')

        #print "** INITIALIZING Magicwand"

        self.pluginIsActive = False
        self.dockwidget = None

        self.output_layer = None


    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('Magicwand', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        text = "Magic Wand"
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToVectorMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action


    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/magic_wand/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u''),
            callback=self.run,
            parent=self.iface.mainWindow())

    #--------------------------------------------------------------------------

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""

        #print "** CLOSING Magicwand"

        # disconnects
        self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)

        # remove this statement if dockwidget is to remain
        # for reuse if plugin is reopened
        # Commented next statement since it causes QGIS crashe
        # when closing the docked window:
        # self.dockwidget = None

        self.pluginIsActive = False


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""

        #print "** UNLOAD Magicwand"

        for action in self.actions:
            self.iface.removePluginVectorMenu(
                self.tr(u'&Magic Wand'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    #--------------------------------------------------------------------------

    #actions on mapcanvas clicked
    def click_action(self, point):
        mapSettings = self.iface.mapCanvas().mapSettings()
        image = self.make_image(mapSettings)
        image_analyzer = ImageAnalyzer(image)
        #get slider value
        resize_multiply = self.dockwidget.accuracy_slider.value() / 100
        threshold = 100 - self.dockwidget.threshold_slider.value()
        bin_index = image_analyzer.to_binary(point, resize_multiply, threshold)

        polygon_maker = PolygonMaker(self.iface.mapCanvas(), bin_index)
        project_crs = QgsProject.instance().crs()
        single_mode = self.dockwidget.single_mode.isChecked()
        selected_layer_id = self.dockwidget.layerComboBox.currentData()

        polygon_maker.make_polygons(point, crs=project_crs, single_mode=single_mode, layer_id=selected_layer_id)

        selected_index = self.dockwidget.layerComboBox.currentIndex()
        self.reload_combo_box()
        self.dockwidget.layerComboBox.setCurrentIndex(selected_index)
        self.canvas.refreshAllLayers()
        
        return

    #make and return QImage from MapCanvas
    def make_image(self, mapSettings):
        image = QImage(mapSettings.outputSize(), QImage.Format_RGB32)
        p = QPainter()
        p.begin(image)
        mapRenderer = QgsMapRendererCustomPainterJob(mapSettings, p)
        mapRenderer.start()
        mapRenderer.waitForFinished()
        p.end()
        return image

    def enable_magicwand(self):
        ct = ClickTool(self.iface,  self.click_action)
        self.previous_map_tool = self.iface.mapCanvas().mapTool()
        self.iface.mapCanvas().setMapTool(ct)

    def init_sliders(self):
        self.dockwidget.accuracy_slider.setMinimum(20)
        self.dockwidget.accuracy_slider.setMaximum(100)
        self.dockwidget.accuracy_slider.setSingleStep(20)
        self.dockwidget.accuracy_slider.setValue(60)
        
        self.dockwidget.threshold_slider.setMinimum(10)
        self.dockwidget.threshold_slider.setMaximum(90)
        self.dockwidget.threshold_slider.setSingleStep(10)
        self.dockwidget.threshold_slider.setValue(50)

    def reload_combo_box(self):
        self.dockwidget.layerComboBox.clear()
        self.dockwidget.layerComboBox.addItem('===New Layer===',0)
        layers = QgsProject.instance().mapLayers()
        for key, layer in layers.items():
            if layer.type() == QgsMapLayer.VectorLayer:
                #key is ID of each layers
                self.dockwidget.layerComboBox.addItem(layer.name(),key)

    def run(self):
        """Run method that loads and starts the plugin"""

        if not self.pluginIsActive:
            self.pluginIsActive = True

            #print "** STARTING Magicwand"

            # dockwidget may not exist if:
            #    first run of plugin
            #    removed on close (see self.onClosePlugin method)
            if self.dockwidget == None:
                # Create the dockwidget (after translation) and keep reference
                self.dockwidget = MagicwandDockWidget()

            # connect to provide cleanup on closing of dockwidget
            self.dockwidget.closingPlugin.connect(self.onClosePlugin)

            # show the dockwidget
            self.iface.addDockWidget(Qt.TopDockWidgetArea, self.dockwidget)
            self.dockwidget.show()

            ct = ClickTool(self.iface,  self.click_action)
            self.previous_map_tool = self.iface.mapCanvas().mapTool()
            self.iface.mapCanvas().setMapTool(ct)

            self.dockwidget.enable_button.clicked.connect(self.enable_magicwand)

            QgsProject.instance().layersAdded.connect(self.reload_combo_box)
            QgsProject.instance().layersRemoved.connect(self.reload_combo_box)
            self.reload_combo_box()
            self.init_sliders()
