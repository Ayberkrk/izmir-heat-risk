from core.paths import resolve_pbf_path


def test_resolve_pbf_path_prefers_standard_name(tmp_path, monkeypatch):
    monkeypatch.setattr("core.paths.city_data_raw", lambda city_id: tmp_path)
    (tmp_path / "testcity.osm.pbf").touch()
    (tmp_path / "aegean-latest.osm.pbf").touch()

    assert resolve_pbf_path("testcity") == tmp_path / "testcity.osm.pbf"


def test_resolve_pbf_path_falls_back_to_legacy_izmir_name(tmp_path, monkeypatch):
    # Şehir ayrımı eklenmeden önce İzmir'in diskte zaten indirilmiş
    # `aegean-latest.osm.pbf` dosyası var - yeniden indirmeyi tetiklememesi
    # gerekir (bkz. core/paths.py, resolve_pbf_path docstring'i).
    monkeypatch.setattr("core.paths.city_data_raw", lambda city_id: tmp_path)
    (tmp_path / "aegean-latest.osm.pbf").touch()

    assert resolve_pbf_path("izmir") == tmp_path / "aegean-latest.osm.pbf"


def test_resolve_pbf_path_returns_standard_name_when_neither_exists(tmp_path, monkeypatch):
    # Yeni bir şehir için legacy dosya hiç var olmaz - standart ad
    # döndürülüp indirme akışına bırakılmalı.
    monkeypatch.setattr("core.paths.city_data_raw", lambda city_id: tmp_path)

    assert resolve_pbf_path("newcity") == tmp_path / "newcity.osm.pbf"
