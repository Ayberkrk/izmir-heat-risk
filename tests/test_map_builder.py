from core.map_builder import _round_coords, _slugify


def test_slugify_handles_turkish_characters():
    assert _slugify("Aşırı Kritik") == "asiri-kritik"
    assert _slugify("Çok sıcak") == "cok-sicak"


def test_slugify_collapses_repeated_separators():
    assert _slugify("  Çok   Yüksek!! ") == "cok-yuksek"


def test_round_coords_rounds_nested_coordinate_floats():
    geo = {"type": "Feature", "geometry": {"type": "LineString",
           "coordinates": [[27.123456789, 38.987654321], [27.0, 38.0]]}}
    result = _round_coords(geo)
    assert result["geometry"]["coordinates"] == [[27.12346, 38.98765], [27.0, 38.0]]


def test_round_coords_leaves_properties_untouched():
    # properties içindeki sayısal değerler koordinat değil - yuvarlanmamalı
    # (ör. bir HVI yüzdesi 27.123456 hassasiyetini korumalı).
    geo = {"type": "Feature", "properties": {"hvi_percentage": 27.123456789},
           "geometry": {"type": "Point", "coordinates": [27.123456789, 38.1]}}
    result = _round_coords(geo)
    assert result["properties"]["hvi_percentage"] == 27.123456789
    assert result["geometry"]["coordinates"] == [27.12346, 38.1]
