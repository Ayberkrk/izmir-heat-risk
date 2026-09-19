"""Şanlıurfa'ya özel demografi adapter'ı.

Eskişehir'deki gibi, Şanlıurfa Büyükşehir Belediyesi'nin İzmir'inkine
benzer bir CKAN açık veri portalı bulunamadı; bu yüzden nüfus/yaş verisi
TÜİK'in resmi, herkese açık yayınlarından statik referans CSV'ler olarak
alındı (bkz. modül dizini):

  - `ilce_nufus.csv`: Eyyübiye, Haliliye ve Karaköprü'nün 2025 ADNKS
    toplam nüfusu (TÜİK, Adrese Dayalı Nüfus Kayıt Sistemi).
    **Önemli sınırlama 1**: yaşlı/çocuk oranı için ilçe bazlı bir TÜİK
    yayını bulunamadı - Eskişehir adapter'ındaki gibi Şanlıurfa İLİ'nin
    2025 genel yaş dağılımı (%4,5 yaşlı) her üç ilçeye de aynı şekilde
    uygulandı.
    **Önemli sınırlama 2 (Eskişehir'den farklı, ek bir yaklaşım)**:
    TÜİK'in il düzeyinde herkese açık yayınladığı "çocuk nüfus oranı"
    resmi olarak 0-17 yaş tanımını kullanıyor (bkz. TÜİK/UNICEF
    "Türkiye'deki Çocuklar 2024" raporu, "Çocuk: 18 yaş altı birey"
    tanımı) - projenin geri kalanının (İzmir/Eskişehir adapter'ları,
    `core/hvi.py`) kullandığı 0-14 tanımıyla BİREBİR aynı değil.
    Şanlıurfa için il düzeyinde ayrı bir 0-14 yayını bulunamadığından
    `COCUK_ORAN` burada TÜİK'in kendi 0-17 rakamı (%43,3, ADNKS 2025) -
    bu, çocuk nüfus bileşenini gerçek 0-14 oranından biraz yüksek
    gösterebilir (15-17 yaş grubunu da içerdiği için). İl düzeyinde
    doğrulanmış bir 0-14 rakamı bulunursa bu satır güncellenmelidir.
  - `sege_2022_ilce.csv`: T.C. Sanayi ve Teknoloji Bakanlığı'nın resmi
    SEGE-2022 raporundaki (baka.gov.tr üzerinden erişilen PDF, Şanlıurfa
    tablosu) Karaköprü (Türkiye geneli 232.), Haliliye (304.) ve
    Eyyübiye (688.) skorları - İzmir/Eskişehir'deki dosyayla aynı
    format/kaynak.
  - Nüfus yoğunluğu da ilçe bazlı sabit bir değer olarak uygulanıyor
    (ilçe toplam nüfusu / ilçe toplam alanı) - Eskişehir adapter'ındaki
    aynı sınırlama burada da geçerli (mahalle içi eşitsizlik yakalanmaz).

Kentsel çekirdek seçimi: Haliliye/Eyyübiye/Karaköprü'nün idari (OSM
admin_level=6) sınırları, şehrin çok ötesine uzanan geniş bir kırsal/
tarımsal hinterlandı da kapsıyor (Harran ovası yönünde onlarca km) -
`config.yaml`'daki bbox bu yüzden tam idari sınır değil, gerçek kentsel
dokunun (küçük/yoğun mahalleler) kümelendiği alan olarak belirlendi.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from core.city_config import CityConfig
from core.text_utils import normalize_name

_CITY_DIR = Path(__file__).resolve().parent
ILCE_NUFUS_CSV_PATH = _CITY_DIR / "ilce_nufus.csv"
SEGE_CSV_PATH = _CITY_DIR / "sege_2022_ilce.csv"


def fetch_population_data(config: CityConfig) -> dict[str, Path]:
    """Nüfus verisi statik referans CSV olarak repoyla birlikte geldiği için
    indirilecek bir şey yok - arayüz uyumluluğu için boş sözlük döner.
    """
    return {}


def build_neighborhood_layer(pbf_path: Path, population_paths: dict[str, Path], config: CityConfig) -> gpd.GeoDataFrame:
    """Mahalle sınırlarını ilçe bazlı nüfus yoğunluğu, yaşlı/çocuk oranı ve
    sosyoekonomik skorla zenginleştirir (bkz. modül docstring'indeki
    sınırlamalar - hepsi ilçe seviyesinde, mahalle seviyesinde değil).
    """
    west, south, east, north = config.bbox
    osm_gdf = gpd.read_file(pbf_path, layer="multipolygons", bbox=(west, south, east, north))

    ilce_gdf = osm_gdf[
        (osm_gdf["admin_level"] == config.admin_level_ilce) & (osm_gdf["boundary"] == "administrative")
    ][["name", "geometry"]].rename(columns={"name": "ilce_adi"}).reset_index(drop=True)

    mahalle_gdf = osm_gdf[
        (osm_gdf["admin_level"] == config.admin_level_mahalle) & (osm_gdf["boundary"] == "administrative")
    ][["name", "geometry"]].rename(columns={"name": "mahalle_adi"}).reset_index(drop=True)

    mahalle_utm = mahalle_gdf.to_crs(config.crs)
    mahalle_gdf["centroid"] = mahalle_utm.geometry.centroid.to_crs("EPSG:4326")
    mahalle_pts = mahalle_gdf.set_geometry("centroid")[["mahalle_adi", "centroid"]]
    mahalle_pts = mahalle_pts.rename(columns={"centroid": "geometry"}).set_geometry("geometry")
    mahalle_pts.crs = mahalle_gdf.crs

    joined = gpd.sjoin(mahalle_pts, ilce_gdf, how="left", predicate="within")
    mahalle_gdf["ilce_adi"] = joined["ilce_adi"].values
    mahalle_gdf = mahalle_gdf.drop(columns=["centroid"]).dropna(subset=["ilce_adi"])
    mahalle_gdf["ilce_norm"] = mahalle_gdf["ilce_adi"].apply(normalize_name)

    # İlçe alanı buradan (OSM sınırından) hesaplanır - TÜİK'in kendi alan
    # rakamı yerine, mahalle-ilçe eşlemesiyle aynı geometriden türetilerek
    # tutarlılık sağlanır.
    ilce_gdf["ilce_norm"] = ilce_gdf["ilce_adi"].apply(normalize_name)
    ilce_utm = ilce_gdf.to_crs(config.crs)
    ilce_alan_km2 = (ilce_utm.geometry.area / 1e6).rename("ilce_alan_km2")
    ilce_alan_km2.index = ilce_gdf["ilce_norm"]

    nufus = pd.read_csv(ILCE_NUFUS_CSV_PATH, sep=";", encoding="utf-8")
    nufus["ilce_norm"] = nufus["ILCE"].apply(normalize_name)
    nufus = nufus.set_index("ilce_norm").join(ilce_alan_km2, how="left")
    nufus["nufus_yogunlugu"] = nufus["NUFUS"] / nufus["ilce_alan_km2"]

    mahalle_gdf = mahalle_gdf.merge(
        nufus[["nufus_yogunlugu", "YASLI_ORAN", "COCUK_ORAN"]].rename(
            columns={"YASLI_ORAN": "yasli_oran", "COCUK_ORAN": "cocuk_oran"}
        ),
        left_on="ilce_norm", right_index=True, how="left",
    )

    sege = pd.read_csv(SEGE_CSV_PATH, sep=";", encoding="utf-8")
    sege["ilce_norm"] = sege["ILCE"].apply(normalize_name)
    sege_skor = sege.set_index("ilce_norm")["SKOR"].rename("sosyoekonomik_skor")
    mahalle_gdf = mahalle_gdf.merge(sege_skor, left_on="ilce_norm", right_index=True, how="left")

    return mahalle_gdf
