from dataclasses import dataclass, field

import numpy as np
import rasterio
from rasterio.transform import from_origin

from core.satellite import is_valid_geotiff, select_best_scenes_per_tile


# --- is_valid_geotiff: dosya var mı VE gerçekten açılabiliyor mu ---

def test_is_valid_geotiff_returns_false_for_missing_file(tmp_path):
    assert is_valid_geotiff(tmp_path / "yok.tif") is False


def test_is_valid_geotiff_returns_false_for_corrupt_file(tmp_path):
    # Yarıda kesilen bir indirme - dosya var ama geçerli bir GeoTIFF değil.
    corrupt = tmp_path / "bozuk.tif"
    corrupt.write_bytes(b"bu bir GeoTIFF degil")
    assert is_valid_geotiff(corrupt) is False


def test_is_valid_geotiff_returns_true_for_a_real_geotiff(tmp_path):
    path = tmp_path / "gecerli.tif"
    profile = {
        "driver": "GTiff", "height": 4, "width": 4, "count": 1, "dtype": "float32",
        "crs": "EPSG:32635", "transform": from_origin(0, 40, 10, 10), "nodata": -9999.0,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.zeros((4, 4), dtype="float32"), 1)
    assert is_valid_geotiff(path) is True


# --- select_best_scenes_per_tile: saf, network gerektirmeyen seçim mantığı ---

@dataclass
class _FakeItem:
    """pystac.Item'ın select_best_scenes_per_tile'ın kullandığı yüzeyi
    (`.id`, `.properties[...]`) - gerçek STAC/network olmadan test için."""
    id: str
    properties: dict = field(default_factory=dict)


def _fake_item(scene_id: str, wrs_path: int, wrs_row: int, cloud_cover: float) -> _FakeItem:
    return _FakeItem(scene_id, {
        "landsat:wrs_path": wrs_path, "landsat:wrs_row": wrs_row, "eo:cloud_cover": cloud_cover,
    })


def test_select_best_scenes_per_tile_default_matches_old_single_scene_behavior():
    # max_per_tile=1 (varsayılan) - önceki min(..., key=cloud_cover)
    # davranışıyla birebir aynı olmalı (regresyon güvencesi).
    items = [
        _fake_item("a", 180, 33, 20.0),
        _fake_item("b", 180, 33, 5.0),   # en temiz - bu seçilmeli
        _fake_item("c", 180, 33, 15.0),
        _fake_item("d", 181, 33, 8.0),   # farklı karo - ayrı seçilir
    ]

    result = select_best_scenes_per_tile(items, max_per_tile=1)

    assert [i.id for i in result[(180, 33)]] == ["b"]
    assert [i.id for i in result[(181, 33)]] == ["d"]


def test_select_best_scenes_per_tile_returns_top_n_sorted_by_cloud_cover():
    items = [
        _fake_item("a", 180, 33, 20.0),
        _fake_item("b", 180, 33, 5.0),
        _fake_item("c", 180, 33, 15.0),
        _fake_item("d", 180, 33, 1.0),
        _fake_item("e", 180, 33, 30.0),
    ]

    result = select_best_scenes_per_tile(items, max_per_tile=3)

    assert [i.id for i in result[(180, 33)]] == ["d", "b", "c"]


def test_select_best_scenes_per_tile_returns_fewer_than_max_if_not_enough_candidates():
    items = [_fake_item("a", 180, 33, 10.0), _fake_item("b", 180, 33, 5.0)]

    result = select_best_scenes_per_tile(items, max_per_tile=5)

    assert len(result[(180, 33)]) == 2


def test_select_best_scenes_per_tile_treats_missing_cloud_cover_as_worst():
    items = [_fake_item("a", 180, 33, 10.0), _FakeItem("b", {"landsat:wrs_path": 180, "landsat:wrs_row": 33})]

    result = select_best_scenes_per_tile(items, max_per_tile=1)

    assert [i.id for i in result[(180, 33)]] == ["a"]


def test_select_best_scenes_per_tile_empty_input_returns_empty_dict():
    assert select_best_scenes_per_tile([], max_per_tile=1) == {}
