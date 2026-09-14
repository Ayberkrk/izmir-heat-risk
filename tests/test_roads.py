import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from core.city_config import CityConfig
from core.roads import compute_road_risk_timeseries

CRS = "EPSG:32635"


def _write_lst_tif(path, region_values):
    """20x20, 10 m'lik sentetik bir LST rasteri yazar.

    `region_values`: [(row_slice, col_slice, value), ...] - geri kalan
    pikseller nodata (-9999.0) kalır, bu da gerçek bir sahnenin bulut/QA
    maskesiyle boşluklu kapsamını taklit eder.
    """
    grid = np.full((20, 20), -9999.0, dtype="float32")
    for rows, cols, value in region_values:
        grid[rows, cols] = value
    profile = {
        "driver": "GTiff", "height": 20, "width": 20, "count": 1, "dtype": "float32",
        "crs": CRS, "transform": from_origin(0, 200, 10, 10), "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(grid, 1)


def _make_config() -> CityConfig:
    return CityConfig(
        city_id="testcity", name="Test City", bbox=[0.0, 0.0, 1.0, 1.0], crs=CRS,
        max_cloud_cover=30, osm_pbf_url="http://example.com/x.pbf",
        drive_highway_types=["primary", "secondary"], admin_level_ilce="6",
        admin_level_mahalle="8", population_adapter_path="cities.testcity.adapter",
    )


def _setup_two_roads(tmp_path, monkeypatch):
    """Ortak ölçek ve `delta_lst` mantığını, gerçek OSM/uydu indirmesi
    olmadan doğrulamak için iki sahte yolu ve iki yıllık LST rasterini
    kurar (bkz. compute_road_risk_timeseries docstring'i).

    Road A: 2020'de 30, 2026'da 32 -> ısındı.
    Road B: 2020'de 20, 2026'da 19 -> soğudu (delta_lst == -1, sınır değeri).
    """
    proc_2020, proc_2026 = tmp_path / "proc" / "2020", tmp_path / "proc" / "2026"
    proc_2020.mkdir(parents=True)
    proc_2026.mkdir(parents=True)

    # Road A tamponu üstteki bölgeyi (satır 1-3, sütun 1-3), Road B tamponu
    # alttaki bölgeyi (satır 16-18, sütun 16-18) kapsayacak şekilde konumlandı.
    region_a = (slice(1, 4), slice(1, 4))
    region_b = (slice(16, 19), slice(16, 19))
    _write_lst_tif(proc_2020 / "lst_celsius.tif", [(*region_a, 30.0), (*region_b, 20.0)])
    _write_lst_tif(proc_2026 / "lst_celsius.tif", [(*region_a, 32.0), (*region_b, 19.0)])
    # NDVI de zonal_stats ile aynı çağrıda örneklenir; değeri bu testler
    # için önemsiz, tüm rasteri kaplayan sabit bir değer yeterli.
    _write_lst_tif(proc_2020 / "ndvi.tif", [(slice(0, 20), slice(0, 20), 0.3)])
    _write_lst_tif(proc_2026 / "ndvi.tif", [(slice(0, 20), slice(0, 20), 0.3)])

    road_a_buffer = box(10, 160, 40, 190)  # satır 1-3, sütun 1-3'ü kapsar
    road_b_buffer = box(160, 10, 190, 40)  # satır 16-18, sütun 16-18'i kapsar
    roads_gdf = gpd.GeoDataFrame({
        "name": ["Road A", "Road B"],
        "highway": ["primary", "secondary"],
        "length": [100.0, 100.0],
        "geometry": [road_a_buffer, road_b_buffer],
        "geometry_buffer": [road_a_buffer, road_b_buffer],
    }, crs=CRS)

    output_proc = tmp_path / "outproc"
    output_proc.mkdir()

    monkeypatch.setattr("core.roads.fetch_road_network", lambda config: roads_gdf.copy())
    monkeypatch.setattr(
        "core.roads.year_paths",
        lambda city_id, year, main_year: (tmp_path / "raw", proc_2020 if year == "2020" else proc_2026),
    )
    monkeypatch.setattr("core.roads.city_data_proc", lambda city_id: output_proc)


def test_risk_score_uses_common_scale_across_years(tmp_path, monkeypatch):
    # Yıllar ayrı ayrı min-max'a normalize edilseydi Road A ve Road B her
    # yılda kendi içinde 0/100'e denk gelirdi (her yılda sadece iki yol
    # var); ORTAK ölçekte 2020'nin en sıcak yolu (Road A, 30°C) 2026'nın en
    # sıcak yolundan (Road A, 32°C) daha düşük risk skoru almalı.
    _setup_two_roads(tmp_path, monkeypatch)
    config = _make_config()

    result = compute_road_risk_timeseries(config, ["2020", "2026"], "2026")
    by_name = result.set_index("name")

    assert by_name.loc["Road A", "risk_score_2020"] < by_name.loc["Road A", "risk_score_2026"]
    assert by_name.loc["Road A", "risk_score_2026"] == 100.0  # tüm yılların en sıcağı
    assert by_name.loc["Road B", "risk_score_2026"] == 0.0  # tüm yılların en soğuğu


def test_delta_lst_boundary_value_is_categorized_as_cooled(tmp_path, monkeypatch):
    # degisim_kategori sınırları [-100, -1, 1, 3, 100] - pd.cut varsayılanı
    # sağa kapalı aralıklar üretir, yani delta_lst == -1.0 tam sınırda
    # "Değişmedi" değil "Soğudu" kategorisine düşmeli. Bu, kodun kendisinin
    # zaten doğru yaptığı ama hiçbir testin doğrulamadığı bir sınır durumu.
    _setup_two_roads(tmp_path, monkeypatch)
    config = _make_config()

    result = compute_road_risk_timeseries(config, ["2020", "2026"], "2026")
    by_name = result.set_index("name")

    assert by_name.loc["Road B", "delta_lst"] == -1.0
    assert by_name.loc["Road B", "degisim_kategori"] == "Soğudu"
    assert by_name.loc["Road A", "degisim_kategori"] == "Hafif Isındı"


def test_road_with_no_valid_lst_in_any_year_is_dropped(tmp_path, monkeypatch):
    # Bir yolun tamponu rasterin kapsama alanı dışında kalırsa (ör. bulut
    # maskesi yüzünden tüm pikselleri nodata) `has_all_years` filtresi o
    # yolu sessizce dışarıda bırakmalı - NaN bir HVI bileşeni üretip
    # geometrik ortalamayı bozmak yerine.
    _setup_two_roads(tmp_path, monkeypatch)
    config = _make_config()

    roads_with_gap = gpd.GeoDataFrame({
        "name": ["Road A", "Road B", "Road C (no data)"],
        "highway": ["primary", "secondary", "residential"],
        "length": [100.0, 100.0, 100.0],
        "geometry": [box(10, 160, 40, 190), box(160, 10, 190, 40), box(500, 500, 530, 530)],
        "geometry_buffer": [box(10, 160, 40, 190), box(160, 10, 190, 40), box(500, 500, 530, 530)],
    }, crs=CRS)
    monkeypatch.setattr("core.roads.fetch_road_network", lambda config: roads_with_gap.copy())

    result = compute_road_risk_timeseries(config, ["2020", "2026"], "2026")

    assert "Road C (no data)" not in result["name"].tolist()
    assert len(result) == 2
