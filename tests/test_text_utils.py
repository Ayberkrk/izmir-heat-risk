from core.text_utils import normalize_name


def test_strips_mahallesi_suffix():
    assert normalize_name("Atatürk Mahallesi") == "ATATURK"


def test_leaves_name_without_suffix_unchanged_besides_case():
    assert normalize_name("Cumhuriyet") == "CUMHURIYET"


def test_dotted_and_dotless_turkish_i_normalize_the_same():
    # Python'un varsayılan str.upper() Türkçe kurallarını izlemez: "i".upper()
    # ASCII "I" verir (Türkçe İ değil), "ı".upper() de aynı ASCII "I"ya gider.
    # Yani noktalı/noktasız ayrımı zaten upper() aşamasında kayboluyor; ASCII
    # eşleme tablosu sadece CSV/OSM kaynağında halihazırda büyük "İ" olarak
    # gelen değerleri yakalıyor. Bu test, iki farklı yazımın (OSM "Izmir" ile
    # resmi kaynağın "İzmir" gibi) aynı normalize sonucuna gittiğini doğrular.
    assert normalize_name("izmir") == normalize_name("İzmir") == normalize_name("ızmir")


def test_turkish_special_characters_are_transliterated_to_ascii():
    assert normalize_name("Şirinyer") == "SIRINYER"
    assert normalize_name("Karşıyaka") == "KARSIYAKA"
    assert normalize_name("Üçkuyular") == "UCKUYULAR"
    assert normalize_name("Buca Öğretmenevi") == "BUCA OGRETMENEVI"
    assert normalize_name("Çiğli") == "CIGLI"


def test_surrounding_whitespace_is_stripped_and_internal_whitespace_collapsed():
    assert normalize_name("  Karşıyaka   Merkez  ") == "KARSIYAKA MERKEZ"


def test_only_trailing_mahallesi_is_stripped_not_mid_string_occurrences():
    # "Mahallesi" kelimesi ismin ortasında geçiyorsa (mahalle adının kendisi
    # bu kelimeyi içeriyorsa) silinmemeli - sadece sonda, ayrı bir kelime
    # olarak duran ek kaldırılıyor.
    assert normalize_name("Mahallesi Parkı") == "MAHALLESI PARKI"


def test_non_string_input_is_coerced_to_string():
    # CSV/GeoDataFrame'den gelen bir sütun bazen NaN (float) içerebilir;
    # fonksiyon bunu "NAN" dizgesine çevirip patlamamalı - üst katmandaki
    # composite_key oluşturma zaten bu değerleri eşleşmeyen bir anahtara
    # yönlendirmeyi bekliyor, TypeError'a değil.
    assert normalize_name(float("nan")) == "NAN"
