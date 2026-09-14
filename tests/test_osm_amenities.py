import geopandas as gpd
from shapely.geometry import Point, Polygon

import core.osm_amenities as osm_amenities
from core.city_config import CityConfig
from core.osm_amenities import (
    GREEN_LANDUSE,
    GREEN_LEISURE,
    HEALTH_AMENITIES,
    _other_tags_get,
    load_green_space_polygons,
    load_health_points,
)


# --- _other_tags_get: OGR "osm" şemasının HSTORE benzeri other_tags dizgesi ---

def test_other_tags_get_extracts_a_known_key():
    other_tags = '"amenity"=>"hospital","name"=>"Ege Devlet Hastanesi"'
    assert _other_tags_get(other_tags, "amenity") == "hospital"


def test_other_tags_get_returns_none_for_missing_key():
    other_tags = '"shop"=>"bakery"'
    assert _other_tags_get(other_tags, "amenity") is None


def test_other_tags_get_handles_none_other_tags_column():
    # Hiç ek etiketi olmayan bir OSM elemanı için `other_tags` sütunu NaN/None
    # olabilir - regex'e geçmeden önce erken çıkış yapılmalı.
    assert _other_tags_get(None, "amenity") is None


def test_other_tags_get_finds_key_regardless_of_position():
    # amenity bazen ilk, bazen son sırada olabilir - OGR anahtarları
    # alfabetik sıralar ama her elemanın etiket kümesi farklıdır.
    other_tags = '"opening_hours"=>"24/7","amenity"=>"pharmacy","wheelchair"=>"yes"'
    assert _other_tags_get(other_tags, "amenity") == "pharmacy"


def test_health_and_green_amenity_sets_match_module_constants():
    # Bu küme, load_health_points/load_green_space_polygons'ın hangi OSM
    # etiketlerini "sağlık" veya "yeşil alan" saydığının tek kaynağı;
    # burada donuyor ki bir modül içi yazım hatası (ör. "hospitals") test
    # olmadan fark edilmeden kalmasın.
    assert HEALTH_AMENITIES == {"hospital", "clinic", "pharmacy", "doctors"}
    assert GREEN_LEISURE == {"park", "garden", "nature_reserve"}
    assert GREEN_LANDUSE == {"forest", "grass", "meadow", "recreation_ground"}


def _make_config() -> CityConfig:
    return CityConfig(
        city_id="testcity", name="Test City", bbox=[0.0, 0.0, 1.0, 1.0], crs="EPSG:32635",
        max_cloud_cover=30, osm_pbf_url="http://example.com/x.pbf", drive_highway_types=["primary"],
        admin_level_ilce="6", admin_level_mahalle="8", population_adapter_path="cities.testcity.adapter",
    )


# --- load_green_space_polygons: gerçek fonksiyon, gpd.read_file sahtelenerek ---

def test_load_green_space_polygons_keeps_leisure_or_landuse_match_and_drops_empty_geometry(monkeypatch):
    polys = gpd.GeoDataFrame({
        "leisure": ["park", None, None],
        "landuse": [None, "forest", "industrial"],
        "geometry": [
            Polygon([(0, 0), (1, 0), (1, 1)]),
            Polygon([(0, 0), (1, 0), (1, 1)]),
            Polygon(),  # boş geometri - bkz. fonksiyondaki geometry.notna() & ~is_empty filtresi
        ],
    }, crs="EPSG:4326")

    monkeypatch.setattr(osm_amenities.gpd, "read_file", lambda *a, **kw: polys)

    green = load_green_space_polygons(_make_config(), "dummy.pbf")

    assert len(green) == 2
    assert "industrial" not in green["landuse"].tolist()


# --- load_health_points: nokta katmanındaki other_tags + poligon katmanının birleşimi ---

def test_load_health_points_combines_point_and_polygon_layers(monkeypatch):
    points = gpd.GeoDataFrame({
        "other_tags": ['"amenity"=>"pharmacy"', '"shop"=>"bakery"', None],
        "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
    }, crs="EPSG:4326")
    polys = gpd.GeoDataFrame({
        "amenity": ["hospital", "school"],
        "geometry": [Polygon([(0, 0), (1, 0), (1, 1)]), Polygon([(2, 2), (3, 2), (3, 3)])],
    }, crs="EPSG:4326")

    def fake_read_file(path, layer, bbox=None, columns=None):
        return points if layer == "points" else polys

    monkeypatch.setattr(osm_amenities.gpd, "read_file", fake_read_file)

    health = load_health_points(_make_config(), "dummy.pbf")

    # Eczane (nokta) + hastane (poligon, merkez noktasına indirgenmiş) - bakkal
    # ve okul dışarıda kalmalı.
    assert len(health) == 2
    assert set(health["amenity"]) == {"pharmacy", "hospital"}
    # Poligon merkez noktası, orijinal poligon geometrisi değil, bir Point olmalı.
    assert all(geom.geom_type == "Point" for geom in health.geometry)
