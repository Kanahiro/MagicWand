"""pytest conftest: make the plugin importable as 'plugin_dir' package."""

import os
import sys
import types
from pathlib import Path

import pytest

# The plugin root is this directory. For relative imports like
# `from .click_tool import ClickTool` (in magic_wand.py) to work,
# the plugin root must be importable as a package — not as top-level.
#
# Register a virtual 'plugin_dir' package whose __path__ points to the
# plugin root, so tests can do `from plugin_dir.image_analyzer import ...`.
_plugin_root = Path(__file__).resolve().parent

_pkg = types.ModuleType("plugin_dir")
_pkg.__path__ = [str(_plugin_root)]
sys.modules["plugin_dir"] = _pkg

# Remove the plugin root from sys.path so that plugin modules don't
# shadow QGIS built-in modules. Plugin modules must be imported via
# 'plugin_dir.xxx' instead.
_plugin_root_str = str(_plugin_root)
sys.path[:] = [p for p in sys.path if p not in (_plugin_root_str, "")]


@pytest.fixture(scope="session")
def qgis_plugin_path(qgis_app):
    """Add QGIS's built-in plugin directory to sys.path.

    Depends on qgis_app (provided by pytest-qgis) to ensure
    QgsApplication is fully initialized before querying pkgDataPath().
    """
    from qgis.core import QgsApplication

    qgis_plugins = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")
    if os.path.isdir(qgis_plugins) and qgis_plugins not in sys.path:
        sys.path.append(qgis_plugins)


@pytest.fixture(scope="session")
def native_processing(qgis_plugin_path):
    """Initialize the processing framework with native algorithms."""
    from processing.core.Processing import Processing
    from qgis.analysis import QgsNativeAlgorithms
    from qgis.core import QgsApplication

    Processing.initialize()
    registry = QgsApplication.processingRegistry()
    if registry.providerById("native") is None:
        registry.addProvider(QgsNativeAlgorithms())
