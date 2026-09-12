import numpy as np
import rasterio
from rasterio.transform import from_origin

from core.raster import reproject_to_crs


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
