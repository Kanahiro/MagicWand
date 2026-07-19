# MagicWand
QGIS plugin to make polygon easily and automatically by analyzing MapCanvas.

Supports QGIS 3.44 or later, including QGIS 4.x (Qt6).

https://github.com/user-attachments/assets/c086909c-a9dc-46dc-8622-d834eb156932

*Japan GSI Seamlessphoto*

# Usage
- Click mapcanvas where you want to make polygon: a tentative polygon is shown semi-transparently, like the magic wand tool of image editors.
- A confirmation dialog opens; adjust the Color Threshold while watching the tentative polygon, then press OK to save it (Cancel discards it).
- While the dialog is open, keep clicking the map to add seed points into the same selection — useful when one visual region spans colors beyond the threshold (e.g. a shaded part), instead of loosening the threshold. All seed colors are combined into one color model.
- Check 1 click mode to save polygons immediately on click, without the tentative polygon and its confirmation dialog.
- Polygons are added as layer edits (one undo step per click): press Ctrl+Z to undo a creation, and save the layer edits to make them permanent.
- The polygon is traced from the area connected to the clicked point (flood fill). Colors are compared perceptually (CIELAB delta-E), and the selection follows smooth gradients (region growing) while sharp color edges stop it.

# Processing algorithm

The same magic-wand selection is available as a processing algorithm
`magicwand:polygonizebyseeds` ("Polygonize by seed points"): it takes an
8-bit RGB raster and a seed point layer, and outputs one multipolygon
feature per seed feature (with a `seed_id` attribute). One seed feature
is one selection — all points of a multipoint feature contribute to the
same selection, like clicking multiple points in the interactive
preview. To run it against
styled map layers, render them first with the built-in "Convert map to
raster" algorithm. Works in the model designer, batch mode, and
`qgis_process`.

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
