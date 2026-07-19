# MagicWand
QGIS plugin to make polygon easily and automatically by analyzing MapCanvas.

Supports QGIS 3.44 or later, including QGIS 4.x (Qt6).

# Sample
![QGIS/MagicWand](./img/sample.gif)

# Usage
- Set Color Threshold, and Click mapcanvas where you want to make polygon.
- A polygon is created from the area connected to the clicked point (flood fill), like the magic wand tool of image editors.
- Colors are compared perceptually (CIELAB delta-E), and the selection follows smooth gradients (region growing) while sharp color edges stop it.
- Enable Preview and hover over the map: after the cursor rests for a moment, the polygon that a click would create is shown semi-transparently.

# Development

## Setup

```sh
# https://docs.astral.sh/uv/
uv sync
```

## Lint / Format

```sh
uv run ruff check .
uv run ruff format .
```

## Test

Tests run inside the official QGIS Docker image (same as CI):

```sh
docker run --rm -v "$(pwd)":/plugin -w /plugin qgis/qgis:3.44 sh -c "
  pip3 install --break-system-packages pytest pytest-qgis &&
  xvfb-run -s '+extension GLX -screen 0 1024x768x24' python3 -m pytest tests/ -v
"
```

## Release

Publishing a GitHub Release triggers `.github/workflows/release.yaml`, which
zips the plugin, uploads it as a release asset, and uploads it to
plugins.qgis.org (the release tag is written to `metadata.txt` as the version).

# Contact
kanahiro.iguchi@gmail.com
