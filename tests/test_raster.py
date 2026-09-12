import numpy as np
import rasterio
from rasterio.transform import from_origin

from core.raster import compute_lst, compute_ndvi, qa_invalid_mask, reproject_to_crs


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
