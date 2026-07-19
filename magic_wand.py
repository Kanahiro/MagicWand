import os.path

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QImage, QPainter
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsApplication,
    QgsProject,
    QgsVectorLayer,
    QgsMapRendererCustomPainterJob,
)
from qgis.gui import QgsRubberBand

# Import the code for the DockWidget
from .magic_wand_dockwidget import MagicwandDockWidget

from .click_tool import ClickTool
from .image_analyzer import ImageAnalyzer
from .polygon_maker import PolygonMaker, POLYGON_GEOMETRY, add_features_to_layer
from .preview_session import PreviewSession
from .processing_provider.provider import MagicWandProvider

NEW_LAYER_ITEM_DATA = 0

TENTATIVE_FILL_COLOR = QColor(255, 190, 0, 90)
TENTATIVE_STROKE_COLOR = QColor(255, 140, 0, 200)


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
        locale = QSettings().value("locale/userLocale") or "en"
        locale_path = os.path.join(
            self.plugin_dir, "i18n", f"Magicwand_{locale[0:2]}.qm"
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr("&Magic Wand")
        self.toolbar = self.iface.addToolBar("Magicwand")
        self.toolbar.setObjectName("Magicwand")

        self.pluginIsActive = False
        self.dockwidget = None
        self.map_tool = None
        self.previous_map_tool = None

        self.rubber_band = None
        self.processing_provider = None
        self.preview_session = None

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
        return QCoreApplication.translate("Magicwand", message)

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
        parent=None,
    ):
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
            self.iface.addPluginToVectorMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.add_action(
            icon_path,
            text="Magic Wand",
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

        self.processing_provider = MagicWandProvider()
        QgsApplication.processingRegistry().addProvider(self.processing_provider)

    # --------------------------------------------------------------------------

    def onClosePlugin(self):
        """Cleanup necessary items here when plugin dockwidget is closed"""

        self.cancel_preview_session()

        # restore the map tool which was active before enabling Magic Wand
        if self.previous_map_tool is not None:
            self.canvas.setMapTool(self.previous_map_tool)
            self.previous_map_tool = None

        self.pluginIsActive = False

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""

        self.cancel_preview_session()
        if self.rubber_band is not None:
            self.canvas.scene().removeItem(self.rubber_band)
            self.rubber_band = None

        try:
            QgsProject.instance().layersAdded.disconnect(self.reload_combo_box)
            QgsProject.instance().layersRemoved.disconnect(self.reload_combo_box)
        except TypeError:
            # signals were never connected
            pass

        if self.dockwidget is not None:
            self.dockwidget.closingPlugin.disconnect(self.onClosePlugin)
            self.iface.removeDockWidget(self.dockwidget)
            self.dockwidget.deleteLater()
            self.dockwidget = None

        if self.processing_provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.processing_provider)
            self.processing_provider = None

        for action in self.actions:
            self.iface.removePluginVectorMenu(self.tr("&Magic Wand"), action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar

    # --------------------------------------------------------------------------

    # actions on mapcanvas clicked
    def click_action(self, point):
        """Open a click-to-confirm session: a tentative polygon plus a
        dialog to tune the threshold, while further clicks add seed
        points before saving. With 1 click mode checked the polygon is
        saved immediately instead."""
        if self.preview_session is not None:
            # an open session consumes canvas clicks: each adds a seed
            self.preview_session.handle_canvas_click(point)
            return

        image = self.make_image(self.canvas.mapSettings())

        if self.dockwidget.one_click_checkbox.isChecked():
            crs = QgsProject.instance().crs()
            threshold = 100 - self.dockwidget.threshold_slider.value()
            bin_index = ImageAnalyzer(image).to_binary(point, threshold)
            features = PolygonMaker(self.canvas, bin_index).build_polygons(crs)
            if features:
                self.save_features(features, crs)
            return

        self.preview_session = PreviewSession(self, image, point)

    def save_features(self, features, crs):
        layer_id = self.dockwidget.layerComboBox.currentData()
        output_layer = add_features_to_layer(features, crs, layer_id)

        # keep the output layer selected — in particular, a freshly
        # created layer becomes the target of subsequent clicks
        self.reload_combo_box()
        index = self.dockwidget.layerComboBox.findData(output_layer.id())
        if index >= 0:
            self.dockwidget.layerComboBox.setCurrentIndex(index)
        # make Ctrl+Z reach this layer's undo stack right away
        self.iface.setActiveLayer(output_layer)
        self.canvas.refreshAllLayers()

    # ------------------------------------------------------- tentative polygon

    def show_tentative(self, features):
        band = self.ensure_rubber_band()
        band.reset(POLYGON_GEOMETRY)
        for feature in features:
            band.addGeometry(feature.geometry(), None)

    def ensure_rubber_band(self):
        if self.rubber_band is None:
            self.rubber_band = QgsRubberBand(self.canvas, POLYGON_GEOMETRY)
            self.rubber_band.setFillColor(TENTATIVE_FILL_COLOR)
            self.rubber_band.setStrokeColor(TENTATIVE_STROKE_COLOR)
            self.rubber_band.setWidth(2)
        return self.rubber_band

    def hide_tentative(self):
        if self.rubber_band is not None:
            self.rubber_band.reset(POLYGON_GEOMETRY)

    # -------------------------------------------------------------------------

    # make and return QImage from MapCanvas
    def make_image(self, mapSettings):
        image = QImage(mapSettings.outputSize(), QImage.Format.Format_RGB32)
        p = QPainter()
        p.begin(image)
        mapRenderer = QgsMapRendererCustomPainterJob(mapSettings, p)
        mapRenderer.start()
        mapRenderer.waitForFinished()
        p.end()
        return image

    def cancel_preview_session(self):
        if self.preview_session is not None:
            self.preview_session.cancel()
        self.hide_tentative()

    def start_magicwand(self):
        current_tool = self.canvas.mapTool()
        if current_tool is not None and current_tool is not self.map_tool:
            self.previous_map_tool = current_tool
        self.map_tool = ClickTool(
            self.iface,
            click_callback=self.click_action,
            deactivated_callback=self.cancel_preview_session,
        )
        self.canvas.setMapTool(self.map_tool)

    def reload_combo_box(self):
        self.dockwidget.layerComboBox.clear()
        self.dockwidget.layerComboBox.addItem("===New Layer===", NEW_LAYER_ITEM_DATA)
        layers = QgsProject.instance().mapLayers()
        for key, layer in layers.items():
            # only polygon layers can receive the generated polygons
            if (
                isinstance(layer, QgsVectorLayer)
                and layer.geometryType() == POLYGON_GEOMETRY
            ):
                # key is ID of each layers
                self.dockwidget.layerComboBox.addItem(layer.name(), key)

    def run(self):
        """Run method that loads and starts the plugin"""

        if not self.pluginIsActive:
            self.pluginIsActive = True

            # dockwidget may not exist if:
            #    first run of plugin
            #    removed on close (see self.onClosePlugin method)
            if self.dockwidget is None:
                # Create the dockwidget (after translation) and keep reference
                self.dockwidget = MagicwandDockWidget()
                self.dockwidget.start_button.clicked.connect(self.start_magicwand)
                # connect to provide cleanup on closing of dockwidget
                self.dockwidget.closingPlugin.connect(self.onClosePlugin)
                QgsProject.instance().layersAdded.connect(self.reload_combo_box)
                QgsProject.instance().layersRemoved.connect(self.reload_combo_box)

            # show the dockwidget
            self.iface.addDockWidget(
                Qt.DockWidgetArea.TopDockWidgetArea, self.dockwidget
            )
            self.dockwidget.show()

            self.start_magicwand()

            self.reload_combo_box()
