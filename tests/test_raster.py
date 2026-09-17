import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from core.city_config import CityConfig
from core.raster import (
    build_lst_ndvi_mosaic,
    compute_lst,
    compute_ndvi,
    composite_scene_arrays,
    qa_invalid_mask,
    reproject_to_crs,
)


def _write_synthetic_geotiff(path, crs, value=42.0, size=20, res=30.0,
                              origin_x=500000.0, origin_y=4400000.0):
    transform = from_origin(origin_x, origin_y, res, res)
    data = np.full((size, size), value, dtype="float32")
    profile = {
        "driver": "GTiff", "height": size, "width": size, "count": 1,
        "dtype": "float32", "crs": crs, "transform": transform, "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def test_reproject_to_crs_changes_crs(tmp_path):
    src_path, dst_path = tmp_path / "src.tif", tmp_path / "dst.tif"
    _write_synthetic_geotiff(src_path, "EPSG:32635")

    reproject_to_crs(src_path, dst_path, "EPSG:32636")

    with rasterio.open(dst_path) as dst:
        assert str(dst.crs) == "EPSG:32636"


def test_reproject_to_crs_preserves_pixel_size(tmp_path):
    # stream_mosaic her sahnenin diğerleriyle aynı piksel ızgarasında
    # olduğunu varsayar - reprojeksiyon çözünürlüğü kaydırırsa mozaikleme
    # ValueError ile patlar (bkz. Eskişehir'de bulunan gerçek hata: 30 m
    # yerine hesaplanan "en iyi" çözünürlük birkaç santim kaymıştı).
    src_path, dst_path = tmp_path / "src.tif", tmp_path / "dst.tif"
    _write_synthetic_geotiff(src_path, "EPSG:32635", res=30.0)

    reproject_to_crs(src_path, dst_path, "EPSG:32636")

    with rasterio.open(dst_path) as dst:
        assert abs(abs(dst.transform.a) - 30.0) < 0.01
        assert abs(abs(dst.transform.e) - 30.0) < 0.01


def test_reproject_to_crs_preserves_valid_data(tmp_path):
    src_path, dst_path = tmp_path / "src.tif", tmp_path / "dst.tif"
    _write_synthetic_geotiff(src_path, "EPSG:32635", value=25.5)

    reproject_to_crs(src_path, dst_path, "EPSG:32636")

    with rasterio.open(dst_path) as dst:
        data = dst.read(1)
        assert (data != -9999.0).any()
        assert np.isclose(data[data != -9999.0][0], 25.5, atol=0.5)


# --- QA_PIXEL bulut maskesi -------------------------------------------------
#
# Bit değerleri USGS LSDS-1328'deki QA_PIXEL tanımından: bit 0 fill, bit 1
# dilated cloud, bit 2 cirrus, bit 3 cloud, bit 4 cloud shadow, bit 5 snow,
# bit 6 clear. "Clear" (0b0100_0000 = 64) tek başına hiçbir dışlanan biti
# taşımadığı için geçerli piksel örneği olarak kullanılıyor.
QA_CLEAR = 0b0100_0000
QA_FILL = 0b0000_0001
QA_DILATED_CLOUD = 0b0000_0010
QA_CIRRUS = 0b0000_0100
QA_CLOUD = 0b0000_1000
QA_CLOUD_SHADOW = 0b0001_0000
QA_SNOW = 0b0010_0000


def test_qa_invalid_mask_flags_each_excluded_class():
    qa = np.array(
        [QA_CLEAR, QA_FILL, QA_DILATED_CLOUD, QA_CIRRUS, QA_CLOUD, QA_CLOUD_SHADOW, QA_SNOW],
        dtype=np.uint16,
    )

    invalid = qa_invalid_mask(qa)

    assert invalid.tolist() == [False, True, True, True, True, True, True]


def test_qa_invalid_mask_ignores_confidence_bits_alone():
    # Yüksek bulut güven biti (bit 8) ama CLOUD bayrağının (bit 3) kendisi
    # kapalıyken maskeleme yapılmamalı - sadece sınıf bitlerine bakılır.
    qa_high_confidence_no_cloud_flag = np.array([QA_CLEAR | (0b11 << 8)], dtype=np.uint16)

    invalid = qa_invalid_mask(qa_high_confidence_no_cloud_flag)

    assert invalid.tolist() == [False]


def test_qa_invalid_mask_is_deterministic_across_calls():
    qa = np.array([QA_CLEAR, QA_CLOUD, QA_CLOUD_SHADOW], dtype=np.uint16)

    assert qa_invalid_mask(qa).tolist() == qa_invalid_mask(qa).tolist()


def test_compute_lst_masks_out_qa_invalid_pixels(tmp_path):
    thermal_path = tmp_path / "thermal.tif"
    transform = from_origin(500000.0, 4400000.0, 30.0, 30.0)
    # (149.0 - 149.0) / 0.00341802 = 0 -> 0 Kelvin ofsetiyle ayırt edici
    # olmayan bir değer yerine LST'yi belirgin biçimde sıfırdan farklı
    # yapan sabit bir piksel değeri kullanılıyor.
    thermal = np.full((2, 2), 10000, dtype="uint16")
    profile = {
        "driver": "GTiff", "height": 2, "width": 2, "count": 1,
        "dtype": "uint16", "crs": "EPSG:32635", "transform": transform, "nodata": 0,
    }
    with rasterio.open(thermal_path, "w", **profile) as dst:
        dst.write(thermal, 1)

    qa_mask = np.array([[False, True], [False, False]])

    lst, _ = compute_lst(thermal_path, qa_mask=qa_mask)

    assert np.isnan(lst[0, 1])
    assert not np.isnan(lst[0, 0])
    assert not np.isnan(lst[1, 0])
    assert not np.isnan(lst[1, 1])


def test_compute_ndvi_masks_out_qa_invalid_pixels(tmp_path):
    red_path, nir_path = tmp_path / "red.tif", tmp_path / "nir.tif"
    transform = from_origin(500000.0, 4400000.0, 30.0, 30.0)
    profile = {
        "driver": "GTiff", "height": 2, "width": 2, "count": 1,
        "dtype": "uint16", "crs": "EPSG:32635", "transform": transform, "nodata": 0,
    }
    with rasterio.open(red_path, "w", **profile) as dst:
        dst.write(np.full((2, 2), 8000, dtype="uint16"), 1)
    with rasterio.open(nir_path, "w", **profile) as dst:
        dst.write(np.full((2, 2), 15000, dtype="uint16"), 1)

    qa_mask = np.array([[True, False], [False, False]])

    ndvi = compute_ndvi(red_path, nir_path, qa_mask=qa_mask)

    assert np.isnan(ndvi[0, 0])
    assert not np.isnan(ndvi[0, 1])
    assert not np.isnan(ndvi[1, 0])
    assert not np.isnan(ndvi[1, 1])


# --- composite_scene_arrays: karo başına birden fazla sahnenin medyan kompoziti ---

def test_composite_scene_arrays_single_array_is_unchanged():
    # max_scenes_per_tile=1 (eski varsayılan) davranışı birebir korunmalı.
    arr = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
    result = composite_scene_arrays([arr])
    assert result is arr


def test_composite_scene_arrays_takes_pixelwise_median():
    a = np.array([[10.0, 10.0]], dtype=np.float32)
    b = np.array([[20.0, 20.0]], dtype=np.float32)
    c = np.array([[90.0, 12.0]], dtype=np.float32)  # aykırı değer, [0,0]'da

    result = composite_scene_arrays([a, b, c])

    # Medyan aykırı 90.0'dan etkilenmemeli (ortalama 40.0 olurdu).
    assert result[0, 0] == 20.0
    assert result[0, 1] == 12.0  # median(10, 20, 12)


def test_composite_scene_arrays_ignores_nan_from_qa_masking():
    a = np.array([[np.nan, 5.0]], dtype=np.float32)
    b = np.array([[8.0, 7.0]], dtype=np.float32)
    c = np.array([[12.0, 9.0]], dtype=np.float32)

    result = composite_scene_arrays([a, b, c])

    # [0,0]: sadece b/c geçerli -> median(8, 12) = 10
    assert result[0, 0] == 10.0
    # [0,1]: üçü de geçerli -> median(5, 7, 9) = 7
    assert result[0, 1] == 7.0


def test_composite_scene_arrays_pixel_nan_in_all_scenes_stays_nan():
    a = np.array([[np.nan]], dtype=np.float32)
    b = np.array([[np.nan]], dtype=np.float32)

    result = composite_scene_arrays([a, b])

    assert np.isnan(result[0, 0])


# --- build_lst_ndvi_mosaic: karonun birden fazla sahnesi doğru şekilde kompozitleniyor mu ---

def _write_scene_bands(scene_dir, crs, thermal_raw, size=4, res=30.0):
    """Bir sahnenin dört bandını (kırmızı, NIR, termal, QA_PIXEL) yazar.

    Kırmızı/NIR sabit tutulur (NDVI testin odağı değil); QA_PIXEL tamamı
    "Clear" (bkz. test_raster.py'deki bit tanımları, 0b0100_0000 = 64) -
    hiçbir piksel maskelenmesin diye. Sadece termal bant sahneler arası
    farklılaştırılır ki medyan kompozit gözlemlenebilsin.
    """
    scene_dir.mkdir(parents=True, exist_ok=True)
    transform = from_origin(500000.0, 4400000.0, res, res)
    base_profile = {
        "driver": "GTiff", "height": size, "width": size, "count": 1,
        "crs": crs, "transform": transform,
    }
    with rasterio.open(scene_dir / "band4_red.tif", "w", dtype="uint16", nodata=0, **base_profile) as dst:
        dst.write(np.full((size, size), 8000, dtype="uint16"), 1)
    with rasterio.open(scene_dir / "band5_nir.tif", "w", dtype="uint16", nodata=0, **base_profile) as dst:
        dst.write(np.full((size, size), 15000, dtype="uint16"), 1)
    with rasterio.open(scene_dir / "band10_thermal.tif", "w", dtype="uint16", nodata=0, **base_profile) as dst:
        dst.write(np.full((size, size), thermal_raw, dtype="uint16"), 1)
    with rasterio.open(scene_dir / "band_qa_pixel.tif", "w", dtype="uint16", **base_profile) as dst:
        dst.write(np.full((size, size), 0b0100_0000, dtype="uint16"), 1)


def _make_config(crs) -> CityConfig:
    return CityConfig(
        city_id="testcity", name="Test City", bbox=[27.0, 38.0, 27.1, 38.1], crs=crs,
        max_cloud_cover=30, osm_pbf_url="http://example.com/x.pbf",
        drive_highway_types=["primary"], admin_level_ilce="6", admin_level_mahalle="8",
        population_adapter_path="cities.testcity.adapter",
    )


def test_build_lst_ndvi_mosaic_composites_multiple_scenes_of_the_same_tile(tmp_path, monkeypatch):
    crs = "EPSG:32635"
    data_raw, data_proc = tmp_path / "raw", tmp_path / "proc"
    data_proc.mkdir(parents=True)

    # İki sahne, AYNI karo ("180_33") - farklı termal ham değerlerle,
    # sonucun medyan (bu 2 sahnelik durumda == ortalama) kompozit olduğu
    # doğrulanacak.
    thermal_a, thermal_b = 40000, 50000
    _write_scene_bands(data_raw / "sceneA", crs, thermal_a)
    _write_scene_bands(data_raw / "sceneB", crs, thermal_b)

    scene_metadata = {
        "scenes": [
            {"tile": "180_33", "scene_id": "sceneA", "folder": "sceneA"},
            {"tile": "180_33", "scene_id": "sceneB", "folder": "sceneB"},
        ]
    }
    (data_raw / "scene_metadata.json").write_text(json.dumps(scene_metadata))

    monkeypatch.setattr(
        "core.raster.year_paths", lambda city_id, year, main_year: (data_raw, data_proc)
    )

    config = _make_config(crs)
    lst_path, ndvi_path = build_lst_ndvi_mosaic(config, "2026", "2026")

    def _raw_to_celsius(raw):
        return raw * 0.00341802 + 149.0 - 273.15

    expected_composite_c = (_raw_to_celsius(thermal_a) + _raw_to_celsius(thermal_b)) / 2

    with rasterio.open(lst_path) as src:
        result = src.read(1)
    assert np.isclose(result[0, 0], expected_composite_c, atol=0.05)
    assert ndvi_path.exists()


def test_build_lst_ndvi_mosaic_single_scene_per_tile_is_unaffected(tmp_path, monkeypatch):
    # max_scenes_per_tile=1 (eski varsayılan) davranışı birebir korunmalı -
    # tek sahneli bir karo için sonuç, o sahnenin kendi LST'si olmalı.
    crs = "EPSG:32635"
    data_raw, data_proc = tmp_path / "raw", tmp_path / "proc"
    data_proc.mkdir(parents=True)

    thermal = 42000
    _write_scene_bands(data_raw / "sceneA", crs, thermal)
    scene_metadata = {"scenes": [{"tile": "180_33", "scene_id": "sceneA", "folder": "sceneA"}]}
    (data_raw / "scene_metadata.json").write_text(json.dumps(scene_metadata))

    monkeypatch.setattr(
        "core.raster.year_paths", lambda city_id, year, main_year: (data_raw, data_proc)
    )

    config = _make_config(crs)
    lst_path, _ = build_lst_ndvi_mosaic(config, "2026", "2026")

    expected_c = thermal * 0.00341802 + 149.0 - 273.15
    with rasterio.open(lst_path) as src:
        result = src.read(1)
    assert np.isclose(result[0, 0], expected_c, atol=0.05)
