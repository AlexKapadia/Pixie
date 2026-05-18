"""Exporters for all 5 map_* output types.

PNG uses a future Playwright route (degrades to HTML when unavailable).
GeoJSON / GPX / KML are hand-rolled (no extra deps). HTML emits a
standalone Leaflet page.
"""

from __future__ import annotations

import html as html_mod
import json
from typing import Any

from pixie.exporters import (
    ExporterDegraded,
    ExporterError,
    register_exporter,
)
from pixie.exporters._common import coerce_value, json_default


MAP_TYPES = ("map_points", "map_heatmap", "map_choropleth", "map_polygons", "map_route")


def _features(spec_data: dict[str, Any], map_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if map_type == "map_points":
        for point in spec_data.get("points") or []:
            out.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                              "coordinates": [point.get("lng"), point.get("lat")]},
                "properties": {k: v for k, v in point.items() if k not in {"lat", "lng"}},
            })
    elif map_type == "map_heatmap":
        for cell in spec_data.get("points") or []:
            out.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                              "coordinates": [cell.get("lng"), cell.get("lat")]},
                "properties": {"weight": cell.get("weight", 1.0)},
            })
    elif map_type == "map_choropleth":
        for region in spec_data.get("regions") or []:
            out.append({
                "type": "Feature",
                "geometry": region.get("geometry"),
                "properties": {"value": region.get("value"), "id": region.get("id")},
            })
    elif map_type == "map_polygons":
        for poly in spec_data.get("polygons") or []:
            out.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": poly.get("coordinates", [])},
                "properties": poly.get("properties", {}),
            })
    elif map_type == "map_route":
        coords = [[pt.get("lng"), pt.get("lat")] for pt in spec_data.get("points") or []]
        out.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": spec_data.get("properties", {}),
        })
    return out


def _geojson_bytes(spec_data: dict[str, Any], map_type: str, *, prov: str) -> bytes:
    fc = {
        "type": "FeatureCollection",
        "features": _features(spec_data, map_type),
        "properties": {"_pixie_provenance": prov},
    }
    return json.dumps(fc, indent=2, default=json_default).encode("utf-8")


def _to_geojson(raw, *, prov, output_key, spec, map_type, **_) -> tuple[bytes, str]:
    spec_data = coerce_value(raw) or {}
    return _geojson_bytes(spec_data, map_type, prov=prov), f"{output_key}.geojson"


def _to_gpx(raw, *, prov, output_key, spec, map_type, **_) -> tuple[bytes, str]:
    if map_type not in {"map_points", "map_route"}:
        raise ExporterError(
            f"GPX export not meaningful for {map_type!r}",
            hint="export as GeoJSON, KML, or HTML instead",
        )
    spec_data = coerce_value(raw) or {}
    points = spec_data.get("points") or []
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- {html_mod.escape(prov)} -->",
        '<gpx version="1.1" creator="Pixie" xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    if map_type == "map_points":
        for pt in points:
            lat, lng = pt.get("lat"), pt.get("lng")
            name = html_mod.escape(str(pt.get("name") or pt.get("label") or ""))
            parts.append(f'<wpt lat="{lat}" lon="{lng}"><name>{name}</name></wpt>')
    else:
        parts.append("<rte>")
        for pt in points:
            parts.append(f'<rtept lat="{pt.get("lat")}" lon="{pt.get("lng")}"></rtept>')
        parts.append("</rte>")
    parts.append("</gpx>")
    return "\n".join(parts).encode("utf-8"), f"{output_key}.gpx"


def _to_kml(raw, *, prov, output_key, spec, map_type, **_) -> tuple[bytes, str]:
    spec_data = coerce_value(raw) or {}
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<!-- {html_mod.escape(prov)} -->",
        '<kml xmlns="http://www.opengis.net/kml/2.2">', "<Document>",
        f"<name>{html_mod.escape(output_key)}</name>",
    ]
    if map_type == "map_route":
        coords = " ".join(
            f"{pt.get('lng')},{pt.get('lat')},0"
            for pt in spec_data.get("points") or []
        )
        parts.append(
            "<Placemark><LineString><coordinates>"
            f"{coords}</coordinates></LineString></Placemark>"
        )
    else:
        for feature in _features(spec_data, map_type):
            geom = feature.get("geometry") or {}
            if geom.get("type") == "Point":
                lng, lat = geom.get("coordinates", [0, 0])
                parts.append(
                    f"<Placemark><Point><coordinates>{lng},{lat},0"
                    "</coordinates></Point></Placemark>"
                )
            elif geom.get("type") == "Polygon":
                rings = geom.get("coordinates") or []
                if rings:
                    outer = " ".join(f"{lng},{lat},0" for lng, lat in rings[0])
                    parts.append(
                        "<Placemark><Polygon><outerBoundaryIs><LinearRing>"
                        f"<coordinates>{outer}</coordinates>"
                        "</LinearRing></outerBoundaryIs></Polygon></Placemark>"
                    )
    parts.append("</Document></kml>")
    return "\n".join(parts).encode("utf-8"), f"{output_key}.kml"


def _to_html(raw, *, prov, output_key, spec, map_type, **_) -> tuple[bytes, str]:
    spec_data = coerce_value(raw) or {}
    spec_json = json.dumps(spec_data, default=json_default)
    payload = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="pixie-provenance" content="{html_mod.escape(prov)}">
<title>{html_mod.escape(output_key)}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="anonymous" />
<style>html,body,#map{{height:100%;margin:0}}</style>
</head><body><div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin="anonymous"></script>
<script>
const spec = {spec_json};
const map = L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap contributors', maxZoom: 19
}}).addTo(map);
const features = [];
(spec.points || []).forEach(p => {{
  const m = L.circleMarker([p.lat, p.lng], {{radius: 5, color: '#3b82f6'}}).addTo(map);
  if (p.label) m.bindTooltip(p.label);
  features.push([p.lat, p.lng]);
}});
(spec.polygons || []).forEach(poly => {{
  L.polygon(poly.coordinates.map(r => r.map(([lng, lat]) => [lat, lng]))).addTo(map);
}});
if (spec.points && spec.points.length > 1 && {json.dumps(map_type == 'map_route')}) {{
  L.polyline(spec.points.map(p => [p.lat, p.lng]), {{color: '#3b82f6'}}).addTo(map);
}}
if (features.length) map.fitBounds(features, {{padding: [16, 16]}});
else map.setView([20, 0], 2);
</script></body></html>"""
    return payload.encode("utf-8"), f"{output_key}.html"


def _to_png(raw, *, prov, output_key, spec, map_type, **_) -> tuple[bytes, str]:
    html_bytes, html_name = _to_html(
        raw, prov=prov, output_key=output_key, spec=spec, map_type=map_type,
    )
    raise ExporterDegraded(
        "map PNG export needs Playwright + the /_internal/map-snapshot route; "
        "exported as standalone HTML instead",
        payload=html_bytes, filename=html_name, actual_format="html",
        hint="install Playwright Chromium via `pixie doctor --install-playwright`",
    )


def _bind(map_type: str) -> None:
    def png(raw, **kw):
        return _to_png(raw, map_type=map_type, **kw)

    def html_export(raw, **kw):
        return _to_html(raw, map_type=map_type, **kw)

    def geojson(raw, **kw):
        return _to_geojson(raw, map_type=map_type, **kw)

    def gpx(raw, **kw):
        return _to_gpx(raw, map_type=map_type, **kw)

    def kml(raw, **kw):
        return _to_kml(raw, map_type=map_type, **kw)

    register_exporter(map_type, "png", png, default=True)
    register_exporter(map_type, "html", html_export)
    register_exporter(map_type, "geojson", geojson)
    register_exporter(map_type, "gpx", gpx)
    register_exporter(map_type, "kml", kml)


for _mt in MAP_TYPES:
    _bind(_mt)
