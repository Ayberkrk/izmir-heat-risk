import json

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Polygon

from core.city_config import CityConfig
from core.map_builder import (
    _build_explanation_column,
    _load_night_lst,
    _prepare_layers,
    _prepare_night_data,
    _round_coords,
    _slugify,
    _write_city_stats,
    build_hvi_map,
    swatch,
)

CRS = "EPSG:32635"


def test_slugify_handles_turkish_characters():
    assert _slugify("Aşırı Kritik") == "asiri-kritik"
    assert _slugify("Çok sıcak") == "cok-sicak"


def test_slugify_collapses_repeated_separators():
    assert _slugify("  Çok   Yüksek!! ") == "cok-yuksek"


def test_round_coords_rounds_nested_coordinate_floats():
    geo = {"type": "Feature", "geometry": {"type": "LineString",
           "coordinates": [[27.123456789, 38.987654321], [27.0, 38.0]]}}
    result = _round_coords(geo)
    assert result["geometry"]["coordinates"] == [[27.12346, 38.98765], [27.0, 38.0]]


def test_round_coords_leaves_properties_untouched():
    # properties içindeki sayısal değerler koordinat değil - yuvarlanmamalı
    # (ör. bir HVI yüzdesi 27.123456 hassasiyetini korumalı).
    geo = {"type": "Feature", "properties": {"hvi_percentage": 27.123456789},
           "geometry": {"type": "Point", "coordinates": [27.123456789, 38.1]}}
    result = _round_coords(geo)
    assert result["properties"]["hvi_percentage"] == 27.123456789
    assert result["geometry"]["coordinates"] == [27.12346, 38.1]


def test_swatch_embeds_the_given_hex_color():
    html = swatch("#de2d26")
    assert "background:#de2d26;" in html


def _make_config(**overrides) -> CityConfig:
    defaults = dict(
        city_id="testcity", name="Test City", bbox=[27.0, 38.0, 27.1, 38.1], crs=CRS,
        max_cloud_cover=30, osm_pbf_url="http://example.com/x.pbf",
        drive_highway_types=["primary"], admin_level_ilce="6", admin_level_mahalle="8",
        population_adapter_path="cities.testcity.adapter", raw={},
    )
    defaults.update(overrides)
    return CityConfig(**defaults)


def _make_roads(with_sosyoekonomik: bool = False) -> gpd.GeoDataFrame:
    """İki yol, iki kategori (Düşük/Kritik), iki yıl (2020/2026) içeren
    minimal ama gerçekçi bir `roads_with_hvi.geojson` benzeri GeoDataFrame.
    """
    data = {
        "geometry": [LineString([(27.0, 38.0), (27.001, 38.001)]),
                     LineString([(27.01, 38.01), (27.011, 38.011)])],
        "name": ["A Caddesi", "B Sokak"],
        "mahalle_adi": ["Merkez Mahallesi", "Kenar Mahallesi"],
        "hvi_percentage_2020": [10.0, 70.0],
        "hvi_category_2020": ["Düşük", "Kritik"],
        "hvi_percentage_2026": [15.0, 80.0],
        "hvi_category_2026": ["Düşük", "Kritik"],
        "_label_sicaklik_2020": ["düşük", "yüksek"],
        "_label_agac_2020": ["yüksek", "çok düşük"],
        "_label_sicaklik_2026": ["düşük", "çok yüksek"],
        "_label_agac_2026": ["yüksek", "çok düşük"],
        "_label_saglik": ["yakın", "uzak"],
        "_label_yesil": ["yakın", "uzak"],
        "_label_yapilasma": ["seyrek", "yoğun"],
        "_label_nufus": ["seyrek", "yoğun"],
        "_label_yasli": ["düşük", "yüksek"],
        "_label_cocuk": ["düşük", "yüksek"],
    }
    if with_sosyoekonomik:
        data["_label_sosyoekonomik"] = ["yüksek", "düşük"]
    return gpd.GeoDataFrame(data, crs="EPSG:4326")


def test_build_explanation_column_includes_all_present_components():
    roads = _make_roads(with_sosyoekonomik=True)
    _build_explanation_column(roads, "2020")

    text = roads.loc[0, "_aciklama_str_2020"]
    assert "Sıcaklık: düşük" in text
    assert "Ağaç örtüsü: yüksek" in text
    assert "Hastaneye uzaklık: yakın" in text
    assert "Sosyoekonomik gelişmişlik: yüksek" in text


def test_build_explanation_column_omits_missing_optional_component():
    # sosyoekonomik_skor'u olmayan bir şehir için (ör. güvenilir bir
    # gösterge bulunamadı) tooltip'te "Veri yok" satırı değil, satırın
    # kendisi hiç görünmemeli.
    roads = _make_roads(with_sosyoekonomik=False)
    _build_explanation_column(roads, "2020")

    text = roads.loc[0, "_aciklama_str_2020"]
    assert "Sosyoekonomik" not in text


def test_write_city_stats_computes_top_risk_mahalle(tmp_path, monkeypatch):
    roads = _make_roads()
    monkeypatch.setattr("core.map_builder.DOCS_DIR", tmp_path)
    config = _make_config()

    _write_city_stats(config, roads, ["2020", "2026"], "2026")

    stats = json.loads((tmp_path / "testcity" / "stats.json").read_text())
    assert stats["city_id"] == "testcity"
    assert stats["road_count"] == 2
    # 2026 için Kenar Mahallesi (%80) Merkez Mahallesi'nden (%15) yüksek.
    assert stats["top_risk_mahalle"] == "Kenar Mahallesi"
    assert stats["category_counts"] == {"Düşük": 1, "Kritik": 1}
    assert stats["avg_hvi_percentage"] == pd.Series([15.0, 80.0]).mean().round(1)


def test_prepare_layers_splits_by_category_and_year_and_renames_columns():
    roads = _make_roads()
    data_by_year = _prepare_layers(roads, ["2020", "2026"])

    dusuk_2020 = data_by_year["2020"]["Düşük"]
    kritik_2020 = data_by_year["2020"]["Kritik"]
    assert len(dusuk_2020["features"]) == 1
    assert len(kritik_2020["features"]) == 1

    props = dusuk_2020["features"][0]["properties"]
    # Yıla özel sütunlar (_hvi_str_2020 vb.) yıldan bağımsız ortak adlara
    # yeniden adlandırılmış olmalı - JS tarafı tek bir tooltip alan
    # kümesiyle çalışıyor (bkz. _base_map'teki GeoJsonTooltip fields).
    assert props["_hvi_str"] == "%10"
    assert "Sıcaklık: düşük" in props["_aciklama_str"]
    assert "_hvi_str_2020" not in props


def test_prepare_layers_marks_missing_percentage_as_no_data():
    roads = _make_roads()
    roads.loc[0, "hvi_percentage_2020"] = float("nan")
    data_by_year = _prepare_layers(roads, ["2020"])

    props = data_by_year["2020"]["Düşük"]["features"][0]["properties"]
    assert props["_hvi_str"] == "Veri yok"


def test_prepare_night_data_filters_by_bin_and_drops_empty_bins():
    night_gdf = gpd.GeoDataFrame({
        "mahalle_adi": ["M1", "M2"],
        "gece_lst_c": [18.0, 26.0],
        "_gece_bin": ["Serin", "Çok sıcak"],
        "_gece_lst_str": ["18.0°C", "26.0°C"],
        "geometry": [Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                     Polygon([(2, 0), (2, 1), (3, 1), (3, 0)])],
    }, crs="EPSG:4326")

    result = _prepare_night_data(night_gdf)

    assert set(result.keys()) == {"Serin", "Çok sıcak"}
    assert len(result["Serin"]["features"]) == 1
    # Aradaki hiç veri olmayan kategoriler ("Ilıman", "Orta", "Sıcak")
    # hiç anahtar olarak üretilmemeli - JS tarafı boş bir dosyaya fetch
    # atmaya çalışmamalı.
    assert "Ilıman" not in result


def test_prepare_night_data_returns_empty_dict_when_no_night_layer():
    assert _prepare_night_data(None) == {}


def test_load_night_lst_returns_none_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("core.map_builder.city_data_proc", lambda city_id: tmp_path)
    config = _make_config()

    assert _load_night_lst(config, "2026") is None


def test_load_night_lst_bins_temperature_into_five_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("core.map_builder.city_data_proc", lambda city_id: tmp_path)
    config = _make_config()

    night_gdf = gpd.GeoDataFrame({
        "mahalle_adi": ["M1"], "gece_lst_c": [22.5],
        "geometry": [Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
    }, crs="EPSG:4326")
    night_gdf.to_file(tmp_path / "night_lst_by_mahalle_2026.geojson", driver="GeoJSON")

    result = _load_night_lst(config, "2026")

    assert result is not None
    assert result.loc[0, "_gece_lst_str"] == "22.5°C"
    assert result.loc[0, "_gece_bin"] in {"Serin", "Ilıman", "Orta", "Sıcak", "Çok sıcak"}


def test_build_hvi_map_writes_offline_and_hosted_outputs_with_split_geojson(tmp_path, monkeypatch):
    """Uçtan uca duman testi: build_hvi_map'in iki çıktısı da (bkz. modül
    docstring'i) doğru dosyaları, doğru şehir/kategori/yıl kırılımıyla
    üretiyor mu.
    """
    output_dir = tmp_path / "output"
    docs_dir = tmp_path / "docs"
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()

    monkeypatch.setattr("core.map_builder.OUTPUT_DIR", output_dir)
    monkeypatch.setattr("core.map_builder.DOCS_DIR", docs_dir)
    monkeypatch.setattr("core.map_builder.city_data_proc", lambda city_id: proc_dir)

    roads = _make_roads()
    roads.to_file(proc_dir / "roads_with_hvi.geojson", driver="GeoJSON")
    config = _make_config()

    offline_html = build_hvi_map(config, ["2020", "2026"], "2026")

    assert offline_html == output_dir / "testcity_hvi_map.html"
    assert offline_html.exists()
    assert offline_html.stat().st_size > 0

    hosted_html = docs_dir / "testcity" / "index.html"
    assert hosted_html.exists()

    # _prepare_layers her (kategori, yıl) çifti için bir GeoJSON üretir
    # (5 kategori × 2 yıl = 10 dosya), veri olmayan kategoriler için de -
    # tarayıcı sadece açılan katmanı fetch ettiğinden bu zararsız, ama
    # o dosyaların içeriği boş olmalı; sadece sentetik verinin kullandığı
    # Düşük/Kritik kategorileri dolu olmalı.
    data_dir = docs_dir / "testcity" / "data"
    produced = {f.name for f in data_dir.glob("*.geojson")}
    assert produced == {f"{_slugify(cat)}_{year}.geojson"
                         for cat in ["Düşük", "Orta", "Yüksek", "Kritik", "Aşırı Kritik"]
                         for year in ["2020", "2026"]}

    dusuk_2020 = json.loads((data_dir / "dusuk_2020.geojson").read_text())
    assert len(dusuk_2020["features"]) == 1
    assert dusuk_2020["features"][0]["properties"]["name"] == "A Caddesi"

    orta_2020 = json.loads((data_dir / "orta_2020.geojson").read_text())
    assert orta_2020["features"] == []

    stats = json.loads((docs_dir / "testcity" / "stats.json").read_text())
    assert stats["road_count"] == 2
