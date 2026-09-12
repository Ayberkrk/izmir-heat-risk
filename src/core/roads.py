"""Yol ağı ve zaman serisi risk skoru (sıcaklık + ağaç örtüsü).

Şehirden bağımsızdır: OSM pbf URL'i, yol tipleri ve tampon mesafesi
`CityConfig` üzerinden gelir.
"""

from __future__ import annotations

import pandas as pd
import geopandas as gpd
import rasterio
import rasterstats
import requests

from core.cache import is_cache_valid, write_cache_meta
from core.city_config import CityConfig
from core.paths import city_data_proc, city_data_raw, year_paths

OSM_DOWNLOAD_TIMEOUT_SECONDS = 300

# `compute_road_risk_timeseries` çıktısının formül sürümü - LST/NDVI risk
# skorunun hesaplanma biçimi değiştiğinde artırılmalı (bkz. core/cache.py).
RISK_TIMESERIES_VERSION = 1


def fetch_road_network(config: CityConfig) -> gpd.GeoDataFrame:
    """OSM yol ağını `.osm.pbf` özütünden çeker (Overpass yerine).

    Overpass API büyük bbox'ları onlarca alt sorguya bölüp zaman aşımına
    uğrayabildiği için, bölgesel bir `.pbf` dosyası bir kez indirilip
    yerelden okunuyor - daha öngörülebilir ve hızlı.
    """
    data_raw = city_data_raw(config.city_id)
    pbf_path = data_raw / f"{config.city_id}.osm.pbf"
    legacy_pbf_path = data_raw / "aegean-latest.osm.pbf"
    data_raw.mkdir(parents=True, exist_ok=True)

    # Geriye dönük uyumluluk: İzmir için diskte zaten `aegean-latest.osm.pbf`
    # var; yeniden indirmemek için önce bu köklü dosya adını dener.
    if not pbf_path.exists() and legacy_pbf_path.exists():
        pbf_path = legacy_pbf_path

    if not pbf_path.exists():
        print(f"{config.name} için OSM özütü indiriliyor: {config.osm_pbf_url}")
        r = requests.get(config.osm_pbf_url, stream=True, timeout=OSM_DOWNLOAD_TIMEOUT_SECONDS)
        r.raise_for_status()
        with open(pbf_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)

    west, south, east, north = config.bbox
    roads_all = gpd.read_file(pbf_path, layer="lines", bbox=(west, south, east, north))
    roads = roads_all[roads_all["highway"].notna()].copy()
    roads = roads[roads["highway"].isin(config.drive_highway_types)]
    roads = roads[["geometry", "name", "highway"]].reset_index(drop=True)

    roads_utm = roads.to_crs(config.crs)
    roads["length"] = roads_utm.geometry.length
    roads["geometry_buffer"] = roads_utm.geometry.buffer(config.buffer_meters)
    return roads


def compute_road_risk_timeseries(config: CityConfig, years: list[str], main_year: str,
                                  force: bool = False) -> gpd.GeoDataFrame:
    """Her yıl için yol başına ortalama LST ve NDVI'yi hesaplar.

    LST, ortak bir min-max aralığıyla 0-100 risk skoruna çevrilir. Yıllar
    ayrı ayrı normalize edilseydi aynı sıcaklık farklı yıllarda farklı
    skorlara denk gelirdi - karşılaştırmayı anlamsızlaştırırdı. Bu yüzden
    tüm yılların LST değerleri birleştirilip TEK bir ortak ölçekle ölçülüyor.
    (Aynı gerekçe `core/hvi.py` içindeki HVI yüzdesi ve kategori sınırları
    için de geçerlidir; o zincir orada da korunur.)

    NDVI (ağaç örtüsü/bitki örtüsü proxysi) LST ile aynı buffer'dan, aynı
    zonal_stats çağrısıyla çıkarılır - ekstra veri indirmeye gerek yok,
    zaten hesaplanan mozaikten okunuyor.
    """
    output_path = city_data_proc(config.city_id) / "roads_timeseries.geojson"
    if is_cache_valid(output_path, RISK_TIMESERIES_VERSION, force=force):
        print("roads_timeseries.geojson güncel, atlanıyor")
        return gpd.read_file(output_path)

    roads = fetch_road_network(config)
    # LST/NDVI örneklemesi yol yüzeyine yakın kalmalı, bu yüzden dar tampon
    # (`config.buffer_meters`) kullanılır. Bina yoğunluğu için gereken çok
    # daha geniş tampon `core/hvi.py` içinde ayrıca üretilir.
    roads_buffered = gpd.GeoDataFrame(
        roads[["highway"]], geometry=roads["geometry_buffer"], crs=config.crs
    )

    for year in years:
        _, data_proc = year_paths(config.city_id, year, main_year)
        lst_path = data_proc / "lst_celsius.tif"
        ndvi_path = data_proc / "ndvi.tif"
        with rasterio.open(lst_path) as src:
            raster_crs = src.crs.to_epsg()
        roads_for_join = roads_buffered.to_crs(f"EPSG:{raster_crs}")

        lst_stats = rasterstats.zonal_stats(
            roads_for_join, str(lst_path), stats=["mean"], nodata=-9999.0, all_touched=False
        )
        roads[f"lst_mean_{year}"] = [s["mean"] for s in lst_stats]
        print(f"[{year}] {roads[f'lst_mean_{year}'].notna().sum():,} yolda geçerli LST bulundu")

        ndvi_stats = rasterstats.zonal_stats(
            roads_for_join, str(ndvi_path), stats=["mean"], nodata=-9999.0, all_touched=False
        )
        roads[f"ndvi_mean_{year}"] = [s["mean"] for s in ndvi_stats]

    has_all_years = roads[[f"lst_mean_{y}" for y in years]].notna().all(axis=1)
    roads_valid = roads[has_all_years].copy()

    combined = pd.concat([roads_valid[f"lst_mean_{y}"] for y in years])
    global_min, global_max = combined.min(), combined.max()

    for year in years:
        roads_valid[f"risk_score_{year}"] = (
            (roads_valid[f"lst_mean_{year}"] - global_min) / (global_max - global_min) * 100
        ).round(1)

    first_year, last_year = years[0], years[-1]
    roads_valid["delta_lst"] = (roads_valid[f"lst_mean_{last_year}"] - roads_valid[f"lst_mean_{first_year}"]).round(1)
    roads_valid["delta_risk"] = (roads_valid[f"risk_score_{last_year}"] - roads_valid[f"risk_score_{first_year}"]).round(1)
    roads_valid["degisim_kategori"] = pd.cut(
        roads_valid["delta_lst"], bins=[-100, -1, 1, 3, 100],
        labels=["Soğudu", "Değişmedi", "Hafif Isındı", "Belirgin Isındı"],
    )

    keep_cols = ["geometry", "name", "highway", "length",
                 *[f"lst_mean_{y}" for y in years], *[f"ndvi_mean_{y}" for y in years],
                 *[f"risk_score_{y}" for y in years],
                 "delta_lst", "delta_risk", "degisim_kategori"]
    roads_final = roads_valid[[c for c in keep_cols if c in roads_valid.columns]].copy()
    roads_final["degisim_kategori"] = roads_final["degisim_kategori"].astype(str)
    roads_final = roads_final.set_geometry("geometry").to_crs("EPSG:4326")
    roads_final.to_file(output_path, driver="GeoJSON")
    write_cache_meta(output_path, RISK_TIMESERIES_VERSION)

    print(f"Kaydedildi: {output_path.name} ({len(roads_final):,} yol segmenti)")
    return roads_final
