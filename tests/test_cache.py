from core.cache import is_cache_valid, write_cache_meta


def test_missing_file_is_invalid(tmp_path):
    output_path = tmp_path / "roads_with_hvi.geojson"
    assert is_cache_valid(output_path, version=1) is False


def test_missing_meta_file_is_invalid(tmp_path):
    # Bu mekanizmadan önce üretilmiş bir dosya olabilir - yan meta dosyası
    # yoksa güvenli taraf yeniden hesaplamaktır.
    output_path = tmp_path / "roads_with_hvi.geojson"
    output_path.write_text("{}")
    assert is_cache_valid(output_path, version=1) is False


def test_matching_version_is_valid(tmp_path):
    output_path = tmp_path / "roads_with_hvi.geojson"
    output_path.write_text("{}")
    write_cache_meta(output_path, version=3)
    assert is_cache_valid(output_path, version=3) is True


def test_mismatched_version_is_invalid(tmp_path):
    output_path = tmp_path / "roads_with_hvi.geojson"
    output_path.write_text("{}")
    write_cache_meta(output_path, version=2)
    assert is_cache_valid(output_path, version=3) is False


def test_force_always_invalidates(tmp_path):
    output_path = tmp_path / "roads_with_hvi.geojson"
    output_path.write_text("{}")
    write_cache_meta(output_path, version=3)
    assert is_cache_valid(output_path, version=3, force=True) is False


def test_corrupt_meta_file_is_invalid(tmp_path):
    output_path = tmp_path / "roads_with_hvi.geojson"
    output_path.write_text("{}")
    (tmp_path / "roads_with_hvi.geojson.meta.json").write_text("not json")
    assert is_cache_valid(output_path, version=1) is False
