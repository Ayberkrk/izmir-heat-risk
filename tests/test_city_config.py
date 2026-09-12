import pytest

from core.city_config import validate_config_dict

VALID_CONFIG = {
    "city": {"name": "Test Şehir", "bbox": [27.0, 38.0, 27.5, 38.5], "crs": "EPSG:32635"},
    "osm": {
        "pbf_url": "https://example.com/test.osm.pbf",
        "highway_types": ["primary", "secondary"],
        "admin_level_ilce": 6,
        "admin_level_mahalle": 8,
    },
    "population": {"adapter": "cities.test.adapter"},
}


def test_valid_config_has_no_errors():
    assert validate_config_dict(VALID_CONFIG) == []


def test_missing_top_level_key_is_reported():
    cfg = {k: v for k, v in VALID_CONFIG.items() if k != "population"}
    errors = validate_config_dict(cfg)
    assert any("population" in e for e in errors)


def test_missing_city_key_is_reported():
    cfg = {**VALID_CONFIG, "city": {"name": "Test Şehir", "crs": "EPSG:32635"}}
    errors = validate_config_dict(cfg)
    assert any("bbox" in e for e in errors)


@pytest.mark.parametrize("bad_bbox", [
    [27.0, 38.0, 27.5],           # eksik eleman
    [27.5, 38.0, 27.0, 38.5],     # batı > doğu
    [27.0, 38.5, 27.5, 38.0],     # güney > kuzey
    [200.0, 38.0, 27.5, 38.5],    # geçersiz enlem/boylam
])
def test_invalid_bbox_is_rejected(bad_bbox):
    cfg = {**VALID_CONFIG, "city": {**VALID_CONFIG["city"], "bbox": bad_bbox}}
    errors = validate_config_dict(cfg)
    assert any("bbox" in e for e in errors)


def test_missing_osm_required_key_is_reported():
    cfg = {**VALID_CONFIG, "osm": {"pbf_url": "https://example.com/test.osm.pbf"}}
    errors = validate_config_dict(cfg)
    assert any("highway_types" in e for e in errors)
