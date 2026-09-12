"""İzmir'e özel demografi adapter'ı.

Her yeni şehir bu arayüzü uygulamalıdır (bkz. CONTRIBUTING.md):
  - `fetch_population_data(config) -> dict[str, Path]`
  - `build_neighborhood_layer(pbf_path, population_paths, config) -> gpd.GeoDataFrame`
    En az şu sütunları içermeli: mahalle_adi, ilce_adi, geometry,
    nufus_yogunlugu, yasli_oran, cocuk_oran, sosyoekonomik_skor.

İzmir'e özgü tuhaflıklar:
  - Nüfus/yaş verisi CKAN tabanlı `acikveri.bizizmir.com` portalından, iki
    ayrı dataset olarak (`izmir-ilceleri-yas-grubuna-gore-nufus-bilgileri`
    ve `cinsiyete-gore-mahalle-nufus-bilgileri`) geliyor.
  - Yaş dağılımı sadece **ilçe** seviyesinde mevcut; ilçenin yaşlı/çocuk
    oranı tüm mahallelerine aynı şekilde uygulanır (downscaling).
  - Sosyoekonomik gelişmişlik skoru, T.C. Sanayi ve Teknoloji Bakanlığı,
    Kalkınma Ajansları Genel Müdürlüğü'nün resmi "İlçelerin Sosyo-Ekonomik
    Gelişmişlik Sıralaması Araştırması (SEGE-2022)" raporundan alınan ilçe
    skorlarıdır; `sege_2022_ilce.csv` dosyasındaki değerler o rapordaki
    İzmir satırlarının elle aktarılmış halidir ve resmi yayınla
    karşılaştırılarak doğrulanmalıdır. Skor ilçe seviyesindedir, aynı
    downscaling mantığıyla mahallelere
    uygulanır. Bu, tek seferlik yayımlanmış statik bir resmi rapor
    olduğu için (canlı bir API değil), CKAN'dan indirilmek yerine küçük
    bir referans CSV olarak repoya dahil edilmiştir.
  - Mahalle-ilçe eşlemesi isme göre değil, konumsal sorguyla (`sjoin`,
    centroid içinde mi) yapılır - aynı isimli mahallelerin (bölgede 7 ayrı
    "Atatürk Mahallesi" var) yanlış ilçeyle eşleşmesini önler.
  - Türkçe yer adı normalizasyonu (`normalize_name`) CSV ile OSM
    isimlerini karşılaştırılabilir hale getirir.
"""

from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from core.city_config import CityConfig
from core.paths import city_data_raw

CKAN_REQUEST_TIMEOUT_SECONDS = 30


def ckan_csv_url(ckan_base: str, package_id: str) -> str:
    resp = requests.get(f"{ckan_base}/api/3/action/package_show", params={"id": package_id},
                         timeout=CKAN_REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise ValueError(f"{package_id} için CKAN API başarısız yanıt döndürdü: {payload}")
    for r in payload["result"]["resources"]:
        if r["format"].upper() == "CSV":
            return r["url"]
    raise ValueError(f"{package_id} için CSV kaynağı bulunamadı")


def fetch_population_data(config: CityConfig) -> dict[str, Path]:
    pop_cfg = config.raw["population"]
    ckan_base = pop_cfg["ckan_base"]
    datasets = pop_cfg["datasets"]

    pop_dir = city_data_raw(config.city_id) / "population"
    pop_dir.mkdir(parents=True, exist_ok=True)

    local_paths = {}
    for key, package_id in datasets.items():
        local_path = pop_dir / f"{key}.csv"
        local_paths[key] = local_path
        if local_path.exists():
            continue
        url = ckan_csv_url(ckan_base, package_id)
        r = requests.get(url, timeout=CKAN_REQUEST_TIMEOUT_SECONDS)
        r.raise_for_status()
        # CKAN kaynağı beklenenden farklı bir dosya (ör. HTML hata sayfası)
        # döndürürse burada erken yakalanır; sonraki adımda pd.read_csv
        # anlaşılmaz bir hatayla patlamak yerine.
        head = r.content.lstrip()[:200].lower()
        if len(r.content) < 10 or head.startswith(b"<"):
            raise ValueError(f"{package_id} CSV kaynağı boş/şüpheli görünüyor (CSV değil, HTML olabilir): {url}")
        local_path.write_bytes(r.content)
    return local_paths


def normalize_name(s: str) -> str:
    """Türkçe yer adlarını karşılaştırılabilir standart forma çevirir."""
    s = str(s).upper().strip()
    for tr_char, ascii_char in {"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C"}.items():
        s = s.replace(tr_char, ascii_char)
    s = re.sub(r"\s+MAHALLESI$", "", s)
    return re.sub(r"\s+", " ", s)


CHILD_AGE_GROUPS = {"0-4", "5-9", "10-14"}
SEGE_CSV_PATH = Path(__file__).resolve().parent / "sege_2022_ilce.csv"


def build_neighborhood_layer(pbf_path: Path, population_paths: dict[str, Path], config: CityConfig) -> gpd.GeoDataFrame:
    """Mahalle sınırlarını nüfus yoğunluğu, yaşlı ve çocuk nüfus oranıyla zenginleştirir."""
    west, south, east, north = config.bbox
    osm_gdf = gpd.read_file(pbf_path, layer="multipolygons", bbox=(west, south, east, north))

    ilce_gdf = osm_gdf[
        (osm_gdf["admin_level"] == config.admin_level_ilce) & (osm_gdf["boundary"] == "administrative")
    ][["name", "geometry"]].rename(columns={"name": "ilce_adi"}).reset_index(drop=True)

    mahalle_gdf = osm_gdf[
        (osm_gdf["admin_level"] == config.admin_level_mahalle) & (osm_gdf["boundary"] == "administrative")
    ][["name", "geometry"]].rename(columns={"name": "mahalle_adi"}).reset_index(drop=True)

    # İsim çakışmaları çok yaygın (bölgede 7 ayrı "Atatürk Mahallesi" var);
    # mahalle-ilçe eşlemesi isim yerine konumsal sorguyla (centroid içinde mi) yapılır.
    mahalle_utm = mahalle_gdf.to_crs(config.crs)
    mahalle_gdf["centroid"] = mahalle_utm.geometry.centroid.to_crs("EPSG:4326")
    mahalle_pts = mahalle_gdf.set_geometry("centroid")[["mahalle_adi", "centroid"]]
    mahalle_pts = mahalle_pts.rename(columns={"centroid": "geometry"}).set_geometry("geometry")
    mahalle_pts.crs = mahalle_gdf.crs

    joined = gpd.sjoin(mahalle_pts, ilce_gdf, how="left", predicate="within")
    mahalle_gdf["ilce_adi"] = joined["ilce_adi"].values
    mahalle_gdf = mahalle_gdf.drop(columns=["centroid"]).dropna(subset=["ilce_adi"])

    mahalle_gdf["ilce_norm"] = mahalle_gdf["ilce_adi"].apply(normalize_name)
    mahalle_gdf["mahalle_norm"] = mahalle_gdf["mahalle_adi"].apply(normalize_name)
    mahalle_gdf["composite_key"] = mahalle_gdf["ilce_norm"] + "||" + mahalle_gdf["mahalle_norm"]

    pop = pd.read_csv(population_paths["mahalle_nufus"], sep=";", encoding="utf-8")
    pop["ilce_norm"] = pop["ILCE_ADI"].apply(normalize_name)
    pop["mahalle_norm"] = pop["MAHALLE_ADI"].apply(normalize_name)
    pop["composite_key"] = pop["ilce_norm"] + "||" + pop["mahalle_norm"]
    pop["NUFUS_ERKEK_TOPLAM"] = pd.to_numeric(pop["NUFUS_ERKEK_TOPLAM"], errors="coerce")
    pop["NUFUS_KADIN_TOPLAM"] = pd.to_numeric(pop["NUFUS_KADIN_TOPLAM"], errors="coerce")
    pop["nufus_toplam"] = pop["NUFUS_ERKEK_TOPLAM"] + pop["NUFUS_KADIN_TOPLAM"]

    mahalle_gdf = mahalle_gdf.merge(pop[["composite_key", "nufus_toplam"]], on="composite_key", how="left")

    mahalle_utm = mahalle_gdf.to_crs(config.crs)
    mahalle_gdf["alan_km2"] = mahalle_utm.geometry.area / 1e6
    mahalle_gdf["nufus_yogunlugu"] = mahalle_gdf["nufus_toplam"] / mahalle_gdf["alan_km2"]

    # Yaş dağılımı sadece ilçe seviyesinde mevcut; ilçenin yaşlı/çocuk oranı
    # tüm mahallelerine aynı şekilde uygulanır (downscaling).
    yas = pd.read_csv(population_paths["yas_grubu"], sep=";", encoding="utf-8")
    yas["ERKEK"] = pd.to_numeric(yas["ERKEK"], errors="coerce")
    yas["KADIN"] = pd.to_numeric(yas["KADIN"], errors="coerce")
    yas["toplam"] = yas["ERKEK"] + yas["KADIN"]
    yas["ilce_norm"] = yas["ILCE"].apply(normalize_name)

    def _starting_age(age_group: str) -> int | None:
        m = re.match(r"(\d+)", str(age_group))
        return int(m.group(1)) if m else None

    starting_ages = yas["YAS_GRUBU"].apply(_starting_age)
    yas["yasli_mi"] = starting_ages.apply(lambda a: a is not None and a >= 65)
    yas["cocuk_mu"] = yas["YAS_GRUBU"].isin(CHILD_AGE_GROUPS)

    ilce_toplam = yas.groupby("ilce_norm")["toplam"].sum()
    ilce_yasli = yas[yas["yasli_mi"]].groupby("ilce_norm")["toplam"].sum()
    ilce_cocuk = yas[yas["cocuk_mu"]].groupby("ilce_norm")["toplam"].sum()
    ilce_yasli_oran = (ilce_yasli / ilce_toplam).rename("yasli_oran")
    ilce_cocuk_oran = (ilce_cocuk / ilce_toplam).rename("cocuk_oran")

    mahalle_gdf = mahalle_gdf.merge(ilce_yasli_oran, left_on="ilce_norm", right_index=True, how="left")
    mahalle_gdf = mahalle_gdf.merge(ilce_cocuk_oran, left_on="ilce_norm", right_index=True, how="left")

    # Sosyoekonomik gelişmişlik skoru - resmi SEGE-2022 raporundan (bkz.
    # modül docstring'i), ilçe seviyesinde, aynı downscaling mantığıyla.
    sege = pd.read_csv(SEGE_CSV_PATH, sep=";", encoding="utf-8")
    sege["ilce_norm"] = sege["ILCE"].apply(normalize_name)
    sege_skor = sege.set_index("ilce_norm")["SKOR"].rename("sosyoekonomik_skor")
    mahalle_gdf = mahalle_gdf.merge(sege_skor, left_on="ilce_norm", right_index=True, how="left")

    return mahalle_gdf
