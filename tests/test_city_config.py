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
    ["batı", 38.0, 27.5, 38.5],    # sayısal olmayan koordinat
    [True, 38.0, 27.5, 38.5],      # bool sayısal koordinat kabul edilmemeli
])
def test_invalid_bbox_is_rejected(bad_bbox):
    cfg = {**VALID_CONFIG, "city": {**VALID_CONFIG["city"], "bbox": bad_bbox}}
    errors = validate_config_dict(cfg)
    assert any("bbox" in e for e in errors)


def test_missing_osm_required_key_is_reported():
    cfg = {**VALID_CONFIG, "osm": {"pbf_url": "https://example.com/test.osm.pbf"}}
    errors = validate_config_dict(cfg)
    assert any("highway_types" in e for e in errors)


@pytest.mark.parametrize("bad_crs", ["not-a-crs", "EPSG:999999999", ""])
def test_invalid_crs_is_rejected(bad_crs):
    cfg = {**VALID_CONFIG, "city": {**VALID_CONFIG["city"], "crs": bad_crs}}
    errors = validate_config_dict(cfg)
    assert any("crs" in e for e in errors)


@pytest.mark.parametrize("good_crs", ["EPSG:32635", "EPSG:4326", "EPSG:32636"])
def test_valid_epsg_crs_is_accepted(good_crs):
    cfg = {**VALID_CONFIG, "city": {**VALID_CONFIG["city"], "crs": good_crs}}
    assert validate_config_dict(cfg) == []


@pytest.mark.parametrize("bad_config", [None, [], "city: izmir"])
def test_non_mapping_root_is_reported(bad_config):
    errors = validate_config_dict(bad_config)
    assert errors == ["Yapılandırmanın üst seviyesi bir sözlük olmalı"]


@pytest.mark.parametrize("section", ["city", "osm", "population"])
@pytest.mark.parametrize("bad_value", [[], "geçersiz"])
def test_non_mapping_required_section_is_reported(section, bad_value):
    cfg = {**VALID_CONFIG, section: bad_value}
    errors = validate_config_dict(cfg)
    assert any(f"'{section}' bölümü bir sözlük olmalı" == error for error in errors)
