import pandas as pd

from core.hvi import bucket_5, normalize_0_1


def test_normalize_0_1_maps_min_max_to_0_1():
    result = normalize_0_1(pd.Series([10, 20, 30]))
    assert result.tolist() == [0.0, 0.5, 1.0]


def test_normalize_0_1_constant_series_returns_all_zero():
    # min == max olduğunda (ör. şehrin tamamı aynı sosyoekonomik ilçede)
    # bölme sıfıra düşer - fonksiyon bunun yerine sabit 0 döndürmeli.
    result = normalize_0_1(pd.Series([5, 5, 5]))
    assert (result == 0).all()


def test_normalize_0_1_preserves_index():
    # HVI birleştirme sırasında sonuç orijinal (boşluklu olabilen) yol
    # indeksine geri hizalanıyor - index kayması sessiz bir hataya yol açar.
    s = pd.Series([1, 2, 3], index=[10, 20, 30])
    result = normalize_0_1(s)
    assert result.index.tolist() == [10, 20, 30]


def test_bucket_5_produces_five_labels_for_skewed_data():
    # Çarpık dağılım: 18 yakın değerin yanında iki uç değer. Eşit
    # genişlikte aralıklar bu durumda tüm satırları tek bir etikette
    # toplardı (bkz. bucket_5 docstring'i); yüzdelik dilim tabanlı bölme,
    # değerler birbirinden ayırt edilebildiği sürece (tekrarsız) her zaman
    # 5 etiketin de kullanılmasını garanti etmeli.
    values = pd.Series(list(range(1, 19)) + [1000, 2000])
    labels = ["çok düşük", "düşük", "orta", "yüksek", "çok yüksek"]
    result = bucket_5(values, labels)
    assert set(result.dropna().unique()) == set(labels)


def test_bucket_5_ties_get_average_rank():
    # Aynı değere sahip çok sayıda satır olsa bile (ör. hiç sağlık
    # noktası olmayan bir bölgede tekrar eden mesafe değerleri) fonksiyon
    # patlamamalı ve hâlâ tanımlı etiketler üretmeli.
    values = pd.Series([0, 0, 0, 0, 0])
    labels = ["a", "b", "c", "d", "e"]
    result = bucket_5(values, labels)
    assert result.notna().all()
