import geopandas as gpd
from shapely.geometry import Point, Polygon

import core.osm_amenities as osm_amenities
from core.city_config import CityConfig
from core.osm_amenities import (
    GREEN_LANDUSE,
    GREEN_LEISURE,
    HEALTH_AMENITIES,
    _other_tags_get,
    load_building_centroids,
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


# --- Centroid CRS doğruluğu: önce config.crs'e geçilip merkez orada
# hesaplanmalı, coğrafi (derece) CRS'te değil - aksi halde büyük/dışbükey
# olmayan poligonlarda merkez sistematik olarak kayar. Aşağıdaki poligon
# kasıtlı olarak çarpık/simetrik değil ve geniş bir enlem aralığına
# yayılıyor ki iki hesaplama arasındaki fark ölçülebilir olsun. ---

_SKEWED_POLYGON = Polygon([(27.0, 30.0), (27.3, 45.0), (30.0, 31.0)])


def _expected_projected_centroid(polygon, crs) -> Point:
    return gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs(crs).centroid.to_crs("EPSG:4326").iloc[0]


def _naive_geographic_centroid(polygon) -> Point:
    return gpd.GeoSeries([polygon], crs="EPSG:4326").centroid.iloc[0]


def test_skewed_polygon_fixture_actually_distinguishes_the_two_methods():
    # Test verisinin kendisinin anlamlı olduğunu doğrula: yanlış (coğrafi
    # CRS'te) ve doğru (projeksiyonlu) centroid gerçekten belirgin farklı
    # olmalı, yoksa aşağıdaki testler bug'ı yakalamayan sahte-yeşil testler olur.
    config = _make_config()
    correct = _expected_projected_centroid(_SKEWED_POLYGON, config.crs)
    naive = _naive_geographic_centroid(_SKEWED_POLYGON)
    assert correct.distance(naive) > 0.01  # ~1 km'den fazla fark


def test_load_health_points_polygon_centroid_uses_projected_crs(monkeypatch):
    points = gpd.GeoDataFrame({"other_tags": [None], "geometry": [Point(0, 0)]}, crs="EPSG:4326")
    polys = gpd.GeoDataFrame({"amenity": ["hospital"], "geometry": [_SKEWED_POLYGON]}, crs="EPSG:4326")

    def fake_read_file(path, layer, bbox=None, columns=None):
        return points if layer == "points" else polys

    monkeypatch.setattr(osm_amenities.gpd, "read_file", fake_read_file)
    config = _make_config()

    health = load_health_points(config, "dummy.pbf")

    result_point = health.loc[health["amenity"] == "hospital", "geometry"].iloc[0]
    expected = _expected_projected_centroid(_SKEWED_POLYGON, config.crs)
    naive = _naive_geographic_centroid(_SKEWED_POLYGON)
    assert result_point.distance(expected) < 1e-6
    assert result_point.distance(naive) > 0.01


def test_load_building_centroids_keeps_only_tagged_buildings(monkeypatch):
    polys = gpd.GeoDataFrame({
        "building": ["yes", None],
        "geometry": [_SKEWED_POLYGON, Polygon([(0, 0), (1, 0), (1, 1)])],
    }, crs="EPSG:4326")
    monkeypatch.setattr(osm_amenities.gpd, "read_file", lambda *a, **kw: polys)

    buildings = load_building_centroids(_make_config(), "dummy.pbf")

    assert len(buildings) == 1


def test_load_building_centroids_uses_projected_crs(monkeypatch):
    polys = gpd.GeoDataFrame({"building": ["yes"], "geometry": [_SKEWED_POLYGON]}, crs="EPSG:4326")
    monkeypatch.setattr(osm_amenities.gpd, "read_file", lambda *a, **kw: polys)
    config = _make_config()

    buildings = load_building_centroids(config, "dummy.pbf")

    result_point = buildings["geometry"].iloc[0]
    expected = _expected_projected_centroid(_SKEWED_POLYGON, config.crs)
    naive = _naive_geographic_centroid(_SKEWED_POLYGON)
    assert result_point.distance(expected) < 1e-6
    assert result_point.distance(naive) > 0.01
