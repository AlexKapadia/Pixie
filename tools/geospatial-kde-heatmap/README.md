# Geospatial KDE Heatmap

Kernel density estimation over a CSV of lat/lng (optionally weighted) points. Outputs a Leaflet heatmap, peak coordinates, and a histogram of density values.

## Install
```
cd tools/geospatial-kde-heatmap
uv sync
```

## Test
```
uv run pixie validate geospatial-kde-heatmap --summary
```
