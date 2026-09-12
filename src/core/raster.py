"""LST / NDVI hesaplama ve bellek-güvenli mozaikleme.

Şehirden bağımsızdır - Landsat Collection 2 Level-2 ürünlerinin bant
kalibrasyonu her yerde aynıdır.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import from_bounds as window_from_bounds

from core.city_config import CityConfig
from core.paths import year_paths


def compute_lst(thermal_path: Path) -> tuple[np.ndarray, dict]:
    """Landsat Level-2 termal banttan yüzey sıcaklığını (°C) hesaplar.

    Level-2 ürünlerde USGS bandı zaten sıcaklığa kalibre etmiş olduğu için
    tek yapılan iş ölçek dönüşümü: piksel × 0.00341802 + 149.0 → Kelvin.
    """
    with rasterio.open(thermal_path) as src:
        thermal_raw = src.read(1).astype(np.float32)
        nodata = src.nodata
        profile = src.profile.copy()

    if nodata is not None:
        thermal_raw = np.where(thermal_raw == nodata, np.nan, thermal_raw)

    lst_kelvin = thermal_raw * 0.00341802 + 149.0
    return lst_kelvin - 273.15, profile


def compute_ndvi(red_path: Path, nir_path: Path) -> np.ndarray:
    with rasterio.open(red_path) as src:
        red = src.read(1).astype(np.float32)
        red_nodata = src.nodata
    with rasterio.open(nir_path) as src:
        nir = src.read(1).astype(np.float32)
        nir_nodata = src.nodata

    if red_nodata is not None:
        red = np.where(red == red_nodata, np.nan, red)
    if nir_nodata is not None:
        nir = np.where(nir == nir_nodata, np.nan, nir)

    red_sr = np.where(red * 0.0000275 - 0.2 < 0, np.nan, red * 0.0000275 - 0.2)
    nir_sr = np.where(nir * 0.0000275 - 0.2 < 0, np.nan, nir * 0.0000275 - 0.2)

    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (nir_sr - red_sr) / (nir_sr + red_sr)
    return np.clip(ndvi, -1.0, 1.0)


def save_geotiff(array: np.ndarray, output_path: Path, profile: dict, nodata_val: float = -9999.0) -> None:
    out_profile = profile.copy()
    out_profile.update({"dtype": "float32", "count": 1, "nodata": nodata_val, "compress": "lzw"})
    arr_to_save = np.where(np.isnan(array), nodata_val, array).astype(np.float32)
    with rasterio.open(output_path, "w", **out_profile) as dst:
        dst.write(arr_to_save, 1)
    del arr_to_save


def build_output_profile(temp_paths: list[Path]) -> dict:
    if not temp_paths:
        raise ValueError("build_output_profile() boş bir liste ile çağrıldı - en az bir sahne gerekir")

    bounds_list = []
    for p in temp_paths:
        with rasterio.open(p) as src:
            bounds_list.append(src.bounds)
            res_x, res_y = src.transform.a, -src.transform.e
            out_crs, out_nodata = src.crs, src.nodata

    min_x = min(b.left for b in bounds_list)
    min_y = min(b.bottom for b in bounds_list)
    max_x = max(b.right for b in bounds_list)
    max_y = max(b.top for b in bounds_list)

    out_width = int(round((max_x - min_x) / res_x))
    out_height = int(round((max_y - min_y) / res_y))
    out_transform = Affine(res_x, 0, min_x, 0, -res_y, max_y)

    return {
        "driver": "GTiff", "height": out_height, "width": out_width, "count": 1,
        "dtype": "float32", "crs": out_crs, "transform": out_transform,
        "nodata": out_nodata, "compress": "lzw",
    }


def stream_mosaic(temp_paths: list[Path], out_path: Path, out_profile: dict) -> None:
    """Sahneleri tek tek okuyup diske yazarak mozaikler.

    `rasterio.merge.merge()` tüm çıktıyı RAM'de oluşturur; 8 GB'lık bir
    makinede bu, dört büyük sahne için belleği taşırır. Burada her sahne
    kendi penceresine (window) yazılır, aynı anda RAM'de sadece bir
    sahnenin verisi tutulur.
    """
    nodata_val = out_profile["nodata"]

    with rasterio.open(out_path, "w", **out_profile) as dst:
        fill_row = np.full(out_profile["width"], nodata_val, dtype=np.float32)
        for row in range(out_profile["height"]):
            dst.write(fill_row.reshape(1, -1), 1, window=((row, row + 1), (0, out_profile["width"])))
        del fill_row

    with rasterio.open(out_path, "r+") as dst:
        for p in temp_paths:
            with rasterio.open(p) as src:
                data = src.read(1)
                window = window_from_bounds(*src.bounds, transform=out_profile["transform"])
                window = window.round_offsets().round_lengths()
                existing = dst.read(1, window=window)
                merged = np.where(data != nodata_val, data, existing)
                dst.write(merged, 1, window=window)
                del data, existing, merged
            gc.collect()


def build_lst_ndvi_mosaic(config: CityConfig, year: str, main_year: str) -> tuple[Path, Path]:
    data_raw, data_proc = year_paths(config.city_id, year, main_year)
    data_proc.mkdir(parents=True, exist_ok=True)
    lst_path = data_proc / "lst_celsius.tif"
    ndvi_path = data_proc / "ndvi.tif"

    if lst_path.exists() and ndvi_path.exists():
        print(f"[{year}] mozaik zaten mevcut, atlanıyor")
        return lst_path, ndvi_path

    with open(data_raw / "scene_metadata.json", encoding="utf-8") as f:
        scenes = json.load(f)["scenes"]

    lst_temp_paths, ndvi_temp_paths = [], []
    for s in scenes:
        scene_dir = data_raw / s["folder"]
        lst, profile = compute_lst(scene_dir / "band10_thermal.tif")
        ndvi = compute_ndvi(scene_dir / "band4_red.tif", scene_dir / "band5_nir.tif")

        lst_temp = scene_dir / "lst_temp.tif"
        ndvi_temp = scene_dir / "ndvi_temp.tif"
        save_geotiff(lst, lst_temp, profile)
        save_geotiff(ndvi, ndvi_temp, profile)
        lst_temp_paths.append(lst_temp)
        ndvi_temp_paths.append(ndvi_temp)

        del lst, ndvi, profile
        gc.collect()

    out_profile = build_output_profile(lst_temp_paths)
    print(f"[{year}] mozaikleniyor: {out_profile['width']}x{out_profile['height']} piksel")
    stream_mosaic(lst_temp_paths, lst_path, out_profile)
    stream_mosaic(ndvi_temp_paths, ndvi_path, out_profile)

    return lst_path, ndvi_path
