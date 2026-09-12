"""OSM pbf'inden sağlık hizmeti, yeşil alan ve bina yoğunluğu katmanlarını çıkarır.

Bu üç katman da zaten indirilmiş olan `.osm.pbf` özütünden türetilir - ek
bir dış veri kaynağına ihtiyaç yoktur. Varsayılan OGR "osm" şeması, nokta
katmanında (`points`) `amenity` gibi etiketleri ayrı sütun olarak değil,
`other_tags` içinde HSTORE benzeri bir dizgede tutar; bu yüzden nokta
katmanı için basit bir regex ayrıştırması gerekir. `multipolygons`
katmanında ise `amenity`, `landuse`, `leisure`, `building` zaten birinci
sınıf sütunlardır.
"""

from __future__ import annotations

import re

import geopandas as gpd
import pandas as pd

from core.city_config import CityConfig

HEALTH_AMENITIES = {"hospital", "clinic", "pharmacy", "doctors"}
GREEN_LEISURE = {"park", "garden", "nature_reserve"}
GREEN_LANDUSE = {"forest", "grass", "meadow", "recreation_ground"}

_OTHER_TAG_RE = re.compile(r'"([^"]+)"=>"([^"]*)"')


def _other_tags_get(other_tags: object, key: str) -> str | None:
    if not isinstance(other_tags, str):
        return None
    for tag_key, tag_val in _OTHER_TAG_RE.findall(other_tags):
        if tag_key == key:
            return tag_val
    return None


def load_health_points(config: CityConfig, pbf_path) -> gpd.GeoDataFrame:
    """Hastane/klinik/eczane/doktor noktalarını ve poligonlarını tek katmanda birleştirir."""
    west, south, east, north = config.bbox
    bbox = (west, south, east, north)

    points = gpd.read_file(pbf_path, layer="points", bbox=bbox)
    if "other_tags" in points.columns:
        points = points.copy()
        points["amenity"] = points["other_tags"].apply(lambda t: _other_tags_get(t, "amenity"))
    else:
        points["amenity"] = None
    health_points = points[points["amenity"].isin(HEALTH_AMENITIES)][["geometry", "amenity"]]

    polys = gpd.read_file(pbf_path, layer="multipolygons", bbox=bbox, columns=["amenity", "geometry"])
    health_polys = polys[polys["amenity"].isin(HEALTH_AMENITIES)][["geometry", "amenity"]].copy()
    health_polys["geometry"] = health_polys.geometry.centroid

    combined = pd.concat([health_points, health_polys], ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs=points.crs)


def load_green_space_polygons(config: CityConfig, pbf_path) -> gpd.GeoDataFrame:
    """Park/bahçe/orman/çayır gibi yeşil alan poligonlarını döndürür."""
    west, south, east, north = config.bbox
    # Bina katmanındaki gibi sütun filtresi kullanılıyor: `multipolygons`
    # katmanının tamamını okumak 8 GB RAM'lik bir makinede gereksiz yük.
    polys = gpd.read_file(
        pbf_path, layer="multipolygons", bbox=(west, south, east, north),
        columns=["leisure", "landuse", "geometry"],
    )
    is_green = polys["leisure"].isin(GREEN_LEISURE) | polys["landuse"].isin(GREEN_LANDUSE)
    green = polys[is_green][["geometry", "leisure", "landuse"]].copy()
    return green[green.geometry.notna() & ~green.geometry.is_empty]


def load_building_centroids(config: CityConfig, pbf_path) -> gpd.GeoDataFrame:
    """Bina ayak izlerinin merkez noktalarını döndürür (yoğunluk hesaplamak için).

    Yapılaşma yoğunluğu için tam bina poligonlarıyla (İzmir'de ~380 bin
    kayıt) çalışmak yerine sadece merkez noktaları kullanılır - 8 GB RAM'lik
    bir makinede 44 bin yol tampon poligonuna karşı 380 bin tam poligon
    join'i yerine, çok daha hafif nokta-içinde-mi sorgusu koşulur.
    """
    west, south, east, north = config.bbox
    polys = gpd.read_file(
        pbf_path, layer="multipolygons", bbox=(west, south, east, north), columns=["building", "geometry"]
    )
    buildings = polys[polys["building"].notna()][["geometry"]].copy()
    buildings["geometry"] = buildings.geometry.centroid
    return buildings
