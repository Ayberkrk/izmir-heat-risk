"""Gece kentsel ısı adası katmanı (MODIS gece LST, Microsoft Planetary Computer).

Landsat'ın gece geçişi pratikte kullanılamaz (termal bandı gündüz sahneleri
için tasarlanmıştır); bu yüzden gece ısı adası etkisi için ayrı bir kaynak
gerekir. MODIS'in "LST_Night_1km" ürünü aynı Planetary Computer altyapısından
(zaten `satellite.py` tarafından kullanılıyor) geliyor - yeni bir sağlayıcı
eklemeye gerek yok.

Önemli fark: Landsat 30 m çözünürlükte, yol segmenti bazlı bir HVI
bileşeni üretebiliyordu. MODIS 1 km çözünürlüğünde - bir piksel bir
mahalleden büyük olabilir. Bu yüzden bu katman HVI'nin onuncu bir
bileşeni DEĞİL, ayrı ve daha kaba (mahalle/şehir ölçeğinde) bir
"gece ısı haritası" görselleştirmesi olarak sunulur; yol bazlı skorla
karıştırılmamalıdır.

Gürültü azaltma: tek bir 8 günlük kompozit yerine, yazın tüm 8 günlük
kompozitlerinin piksel bazlı ortalaması alınır - bu, bulutlu/aksak
gecelerin tek bir dönemi domine etmesini önler (aynı "tek sahne yerine
çoklu örnek" mantığı, README'nin "Metodolojik uyarı" bölümünde Landsat
için de gelecek iyileştirme olarak zaten not edilmişti).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import planetary_computer
import pystac_client
import rasterio
import rasterstats
from rasterio.warp import Resampling, calculate_default_transform, reproject

from core.city_config import CityConfig
from core.paths import city_data_proc

CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "modis-11A2-061"
NIGHT_LST_ASSET = "LST_Night_1km"
KELVIN_SCALE = 0.02  # ham piksel × 0.02 = Kelvin (bkz. koleksiyon raster:bands şeması)
DOWNLOAD_TIMEOUT_SECONDS = 120
OUT_PIXEL_DEGREES = 0.01  # ~1 km - MODIS'in kendi çözünürlüğüyle uyumlu


def fetch_night_lst(config: CityConfig, year: str) -> Path:
    """Yazın tüm 8-günlük MODIS gece LST kompozitlerinin ortalamasını,
    şehrin bbox'ına kırpılmış tek bir GeoTIFF (°C, EPSG:4326) olarak yazar.
    """
    out_path = city_data_proc(config.city_id) / f"night_lst_{year}.tif"
    if out_path.exists():
        print(f"[{year}] night_lst_{year}.tif zaten mevcut, atlanıyor")
        return out_path

    catalog = pystac_client.Client.open(CATALOG_URL, modifier=planetary_computer.sign_inplace)
    search = catalog.search(
        collections=[COLLECTION],
        bbox=config.bbox,
        datetime=f"{year}-06-01/{year}-08-31",
    )
    items = list(search.items())
    if not items:
        raise RuntimeError(
            f"[{year}] {config.name} için bbox={config.bbox} kapsayan MODIS gece LST "
            f"({COLLECTION}) bulunamadı - tarih aralığını genişletmeyi deneyin."
        )
    print(f"[{year}] {len(items)} MODIS 8-günlük kompozit bulundu (gece LST)")

    west, south, east, north = config.bbox
    dst_width = max(int(round((east - west) / OUT_PIXEL_DEGREES)), 1)
    dst_height = max(int(round((north - south) / OUT_PIXEL_DEGREES)), 1)
    dst_transform, _, _ = calculate_default_transform(
        "EPSG:4326", "EPSG:4326", dst_width, dst_height, west, south, east, north,
    )

    sum_c = np.zeros((dst_height, dst_width), dtype=np.float64)
    count = np.zeros((dst_height, dst_width), dtype=np.int32)

    for item in items:
        href = item.assets[NIGHT_LST_ASSET].href
        with rasterio.open(href) as src:
            raw = src.read(1)
            src_crs, src_transform = src.crs, src.transform

        # Ham değer 0 = geçersiz/veri yok (bkz. ürün belgesi) - gerçek bir
        # sıcaklık ölçümüyle karışmaması için NaN'e çevrilir.
        celsius = np.where(raw == 0, np.nan, raw * KELVIN_SCALE - 273.15).astype(np.float32)

        reprojected = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
        reproject(
            source=celsius, destination=reprojected,
            src_transform=src_transform, src_crs=src_crs,
            dst_transform=dst_transform, dst_crs="EPSG:4326",
            resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan,
        )

        valid = ~np.isnan(reprojected)
        sum_c[valid] += reprojected[valid]
        count[valid] += 1

    with np.errstate(invalid="ignore", divide="ignore"):
        mean_c = np.where(count > 0, sum_c / count, np.nan)

    out_profile = {
        "driver": "GTiff", "height": dst_height, "width": dst_width, "count": 1,
        "dtype": "float32", "crs": "EPSG:4326", "transform": dst_transform,
        "nodata": -9999.0, "compress": "lzw",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(np.where(np.isnan(mean_c), -9999.0, mean_c).astype(np.float32), 1)

    valid_ratio = (count > 0).mean()
    print(f"[{year}] gece LST kaydedildi: {out_path.name} "
          f"(geçerli piksel oranı %{valid_ratio * 100:.0f}, {len(items)} kompozitin ortalaması)")
    return out_path


def compute_neighborhood_night_lst(config: CityConfig, pbf_path: Path, night_lst_tif_path: Path, year: str) -> Path:
    """Mahalle sınırları başına ortalama gece LST'sini hesaplar.

    1 km'lik MODIS pikseli çoğu zaman bir mahalleden büyük olduğu için bu
    katman yol segmenti değil, mahalle çözünürlüğünde sunulur - HVI'nin
    yol bazlı bileşenleriyle aynı haritada ama ayrı bir katman olarak
    (bkz. modül docstring'i).
    """
    out_path = city_data_proc(config.city_id) / f"night_lst_by_mahalle_{year}.geojson"
    if out_path.exists():
        print(f"[{year}] night_lst_by_mahalle_{year}.geojson zaten mevcut, atlanıyor")
        return out_path

    west, south, east, north = config.bbox
    osm_gdf = gpd.read_file(pbf_path, layer="multipolygons", bbox=(west, south, east, north))
    mahalle_gdf = osm_gdf[
        (osm_gdf["admin_level"] == config.admin_level_mahalle) & (osm_gdf["boundary"] == "administrative")
    ][["name", "geometry"]].rename(columns={"name": "mahalle_adi"}).reset_index(drop=True)

    stats = rasterstats.zonal_stats(mahalle_gdf, str(night_lst_tif_path), stats=["mean"], nodata=-9999.0)
    mahalle_gdf["gece_lst_c"] = [s["mean"] for s in stats]
    mahalle_gdf = mahalle_gdf.dropna(subset=["gece_lst_c"])
    mahalle_gdf["gece_lst_c"] = mahalle_gdf["gece_lst_c"].round(1)

    mahalle_gdf.to_file(out_path, driver="GeoJSON")
    print(f"[{year}] kaydedildi: {out_path.name} ({len(mahalle_gdf):,} mahalle)")
    return out_path
