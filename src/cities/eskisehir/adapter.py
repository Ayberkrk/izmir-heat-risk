"""Eskişehir'e özel demografi adapter'ı.

İzmir'in aksine Eskişehir Büyükşehir Belediyesi'nin kendi CKAN açık veri
portalı yok; bu yüzden nüfus/yaş verisi TÜİK'in resmi, herkese açık
yayınlarından statik referans CSV'ler olarak alındı (bkz. modül dizini):

  - `ilce_nufus.csv`: Odunpazarı ve Tepebaşı'nın 2025 ADNKS toplam nüfusu
    (TÜİK, Adrese Dayalı Nüfus Kayıt Sistemi) ve yaşlı/çocuk oranı.
    **Önemli sınırlama**: yaşlı/çocuk oranı için ilçe bazlı bir TÜİK
    yayını bulunamadı - bu yüzden Eskişehir İLİ'nin 2025 genel yaş
    dağılımı (%16,5 çocuk, %13,0 yaşlı) her iki ilçeye de aynı şekilde
    uygulandı. İzmir adapter'ı yaş oranını ilçe seviyesinde uyguluyordu
    (mahalle seviyesinde değil); burada bir kademe daha kaba bir yaklaşım
    kullanılıyor (il seviyesi). Gerçek ilçe bazlı oran, il ortalamasından
    belirgin şekilde sapabilir.
  - `sege_2022_ilce.csv`: T.C. Sanayi ve Teknoloji Bakanlığı'nın resmi
    SEGE-2022 raporundaki Odunpazarı (Türkiye geneli 48.) ve Tepebaşı
    (84.) skorları - İzmir'deki dosyayla aynı format/kaynak.
  - Nüfus yoğunluğu da ilçe bazlı sabit bir değer olarak uygulanıyor
    (ilçe toplam nüfusu / ilçe toplam alanı) - mahalle bazlı gerçek nüfus
    dağılımı olmadığı için her mahalle aynı yoğunluğu alır. Bu, gerçek
    mahalle-içi eşitsizliği (ör. bir mahallenin çok daha yoğun olması)
    gizler; İzmir'in mahalle bazlı CKAN nüfus verisiyle mümkün olan
    çözünürlük burada yok.

Bu sınırlamalar bilinçli bir tercih: TÜİK verisi Türkiye'deki her il/ilçe
için mevcut, bu yüzden bu adapter (İzmir'in CKAN'a özel adapter'ının
aksine) İzmir'inkine benzer bir belediye açık veri portalı olmayan
HERHANGİ bir Türkiye şehrine kolayca uyarlanabilir bir şablon oluşturuyor.
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
