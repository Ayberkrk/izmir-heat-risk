"""Çok bileşenli, açıklanabilir Isı Hassasiyet Endeksi (HVI).

Eski sürüm HVI'yi sadece üç bileşenin (Tehlike × Maruziyet × Hassasiyet)
çarpımı olarak hesaplıyordu. Bu modül, değişken sayıda 0-1 normalize
bileşeni birleştirebilecek genel bir yapı sunar; her bileşenin kendi
normalize değeri de nihai skorla birlikte GeoJSON'a yazılır - böylece bir
kullanıcı "bu yolun HVI'si neden yüksek?" sorusuna haritadan doğrudan
cevap bulabilir.

Bileşenler:
  - hazard              : LST risk skoru (yıl bazlı, zaten vardı)
  - exposure             : nüfus yoğunluğu (zaten vardı)
  - sensitivity_yasli     : 65+ nüfus oranı (zaten vardı)
  - sensitivity_cocuk     : 0-14 nüfus oranı (yeni - aynı CSV'den, ek maliyetsiz)
  - sensitivity_agac      : yol tamponundaki ortalama NDVI'nin tersi (yeni -
                             zaten hesaplanan NDVI mozaiğinden, ağaç örtüsü/gölge proxysi)
  - sensitivity_saglik    : en yakın hastane/klinik/eczaneye uzaklık (yeni - OSM'den)
  - sensitivity_yesil     : en yakın park/orman/çayır poligonuna uzaklık (yeni - OSM'den)
  - sensitivity_yapilasma : yol tamponu çevresindeki bina yoğunluğu (yeni - OSM'den)
  - sensitivity_sosyoekonomik : ilçe bazlı sosyoekonomik gelişmişlik skorunun
                             tersi (yeni - resmi SEGE-2022 raporundan, bkz.
                             cities/izmir/adapter.py)

Birleştirme: N adet 0-1 normalize bileşenin **geometrik ortalaması** × 100.
Eski üç bileşenli çarpımsal formül (Tehlike × Maruziyet × Hassasiyet) ile
geometrik ortalama aynı sayıyı vermez ama yolları aynı sırayla dizer (biri
diğerinin küpüdür); geometrik ortalama bu sıralamayı keyfi N'e genelleştirir
ve "bir bileşen sıfıra yakınsa toplam risk de düşük çıkar" özelliğini korur
- ağırlıklı aritmetik ortalama bu özelliği sağlamaz.

Geometrik ortalamanın yan etkisi ve nasıl ele alındığı: `normalize_0_1`
min-max olduğu için her bileşende en az bir satır tam 0 alır ve `eps`
yaklaşımıyla o satırın skoru sert biçimde aşağı çekilir. Bu, "bir bileşen
sıfırsa risk düşüktür" tasarım tercihinin doğal sonucudur; ama bir bileşen
*hatalı* biçimde sıfır üretiyorsa sonucu topluca bozar. Bu yüzden her
bileşenin gerçekten anlamlı bir yayılım ürettiği doğrulanmalıdır - bkz.
`_building_density_per_km2` içindeki sıfır-oranı uyarısı.

Yıllar arası karşılaştırılabilirlik: `hvi_percentage` ve Jenks kategori
sınırları TÜM yılların ortak dağılımından hesaplanır. Her yıl kendi içinde
0-100'e ölçeklenseydi, tanım gereği her yılın en kötü yolu %100 çıkar ve
"2026'da risk arttı" demek imkansız olurdu. LST risk skorunda (`core/roads.py`)
uygulanan ortak ölçek mantığının aynısı burada da geçerlidir.
"""

from __future__ import annotations

import gc

import geopandas as gpd
import jenkspy
import numpy as np
import pandas as pd

from core.cache import is_cache_valid, write_cache_meta
from core.city_config import CityConfig, load_population_adapter
from core.osm_amenities import load_building_centroids, load_green_space_polygons, load_health_points
from core.paths import city_data_proc, city_data_raw

CATEGORY_COLORS_5 = {
    "Düşük": "#3182bd",
    "Orta": "#fdae6b",
    "Yüksek": "#fd8d3c",
    "Kritik": "#de2d26",
    "Aşırı Kritik": "#800026",
}
CATEGORY_ORDER_5 = list(CATEGORY_COLORS_5)

BUCKET_LABELS_5 = ["çok düşük", "düşük", "orta", "yüksek", "çok yüksek"]
BUCKET_LABELS_5_DISTANCE = ["çok yakın", "yakın", "orta", "uzak", "çok uzak"]
BUCKET_LABELS_5_DENSITY = ["çok seyrek", "seyrek", "orta", "yoğun", "çok yoğun"]

# Bina yoğunluğu için yol tamponu, LST örneklemesinde kullanılan dar
# tampondan (varsayılan 10 m) ayrıdır: bina merkez noktaları yol eksenine
# tipik olarak 10 m'den uzakta kaldığı için dar tamponla ölçüm yolların
# yarısından fazlasında 0 çıkıyordu. 150 m, bir yolun çevresindeki kentsel
# doku için makul bir yürüme mesafesi ölçeğidir.
BUILDING_DENSITY_BUFFER_M = 150

# Geometrik ortalama alınmadan önce her bileşenin ölçekleneceği alt sınır
# (gerekçesi `compute_heat_vulnerability_index` içinde).
COMPONENT_FLOOR = 0.05

# Çıktının formül sürümü - bileşen sayısı, birleştirme yöntemi (geometrik
# ortalama), COMPONENT_FLOOR veya BUILDING_DENSITY_BUFFER_M değiştiğinde
# artırılmalı; aksi halde eski `roads_with_hvi.geojson` güncel formülle
# üretilmiş gibi kullanılmaya devam eder (bkz. core/cache.py).
HVI_FORMULA_VERSION = 1


def normalize_0_1(series: pd.Series) -> pd.Series:
    min_v, max_v = series.min(), series.max()
    if max_v == min_v:
        return series * 0
    return (series - min_v) / (max_v - min_v)


def bucket_5(series: pd.Series, labels: list[str]) -> pd.Series:
    """Bir seriyi yüzdelik dilimlerine göre 5 etikete ayırır.

    Eşit genişlikte aralıklar (0-0.2, 0.2-0.4, ...) kullanılmıyor: gerçek
    veriler çok çarpık dağıldığı için birkaç uç değer tüm aralığı ele
    geçiriyor ve etiketler bilgi taşımaz hale geliyordu (ör. yolların
    %91'i "hastaneye çok yakın" çıkıyordu). Sıralamaya (rank) göre
    bölmek, her etiketin yolların yaklaşık beşte birine denk gelmesini
    garanti eder. Eşit değerler ortalama sıra alır, böylece çok sayıda
    tekrar eden değer olsa bile fonksiyon her zaman 5 etiket üretir.
    """
    pct = series.rank(pct=True, method="average")
    return pd.cut(pct, bins=[-0.001, 0.2, 0.4, 0.6, 0.8, 1.001], labels=labels)


def _nearest_distance_m(points_utm: gpd.GeoSeries, targets_wgs84: gpd.GeoDataFrame, crs: str) -> pd.Series:
    """Her nokta için en yakın hedefe olan mesafeyi (metre) döndürür.

    `points_utm`'in orijinal (muhtemelen boşluklu) indeksi korunur; iç
    hesap için 0..n-1 pozisyonel bir indekse geçilip sonda geri eşlenir -
    bu, sjoin_nearest'in eşit mesafede satır çoğaltma davranışına karşı
    orijinal indeks değerlerinin çakışma/boşluk durumundan bağımsız çalışır.
    """
    if len(targets_wgs84) == 0:
        return pd.Series(np.nan, index=points_utm.index)

    targets_utm = targets_wgs84.to_crs(crs)
    left = gpd.GeoDataFrame(geometry=points_utm.reset_index(drop=True), crs=crs)
    joined = gpd.sjoin_nearest(left, targets_utm[["geometry"]], how="left", distance_col="dist_m")
    # sjoin_nearest eşit mesafede birden fazla eşleşme varsa satırı çoğaltabilir;
    # left'in pozisyonel indeksine göre gruplayıp en küçük mesafeyi al.
    nearest = joined.groupby(joined.index)["dist_m"].min()
    values = nearest.reindex(range(len(points_utm))).to_numpy()
    return pd.Series(values, index=points_utm.index)


def _building_density_per_km2(building_centroids_utm: gpd.GeoDataFrame, roads_utm: gpd.GeoDataFrame,
                               buffer_m: int = BUILDING_DENSITY_BUFFER_M, chunk_size: int = 4000) -> pd.Series:
    """Her yolun çevresindeki bina yoğunluğunu (bina/km²) döndürür.

    Yolun etrafına `buffer_m` yarıçapında bir tampon çizilir ve içine merkezi
    düşen bina sayısı tamponun alanına bölünür. Tampon, LST örneklemesinde
    kullanılan dar tampondan (`config.buffer_meters`) kasıtlı olarak ayrıdır -
    gerekçesi `BUILDING_DENSITY_BUFFER_M` yanındaki notta.

    Bellek: sonuç 8 GB RAM'lik bir makinede de üretilebilmeli. Bu yüzden
    geopandas `sjoin` (eşleşen her bina-yol çifti için tam bir satır üretir)
    yerine doğrudan konumsal indeks sorgusu kullanılıyor; bu sorgu sadece iki
    tamsayı dizisi döndürür, geometri kopyalamaz. Yollar ayrıca parça parça
    işlenir, böylece aynı anda yalnızca `chunk_size` kadar tampon poligonu
    bellekte tutulur.
    """
    tree = building_centroids_utm.sindex
    all_index = roads_utm.index
    parts = []

    for start in range(0, len(all_index), chunk_size):
        chunk_index = all_index[start:start + chunk_size]
        buffers = roads_utm.loc[chunk_index].geometry.buffer(buffer_m)
        # query() (tampon, bina) pozisyon çiftlerini verir; satır 0 tampon
        # sırası, satır 1 bina sırasıdır. Sadece saymak yeterli.
        hits = tree.query(buffers, predicate="contains")
        counts = np.bincount(hits[0], minlength=len(buffers))
        area_km2 = buffers.area.to_numpy() / 1e6
        with np.errstate(invalid="ignore", divide="ignore"):
            density = np.where(area_km2 > 0, counts / area_km2, np.nan)
        parts.append(pd.Series(density, index=chunk_index))
        del buffers, hits, counts, area_km2, density
        gc.collect()

    return pd.concat(parts)


def compute_heat_vulnerability_index(config: CityConfig, years: list[str],
                                      roads: gpd.GeoDataFrame, force: bool = False) -> gpd.GeoDataFrame:
    """Çok bileşenli HVI'yi hesaplar; her bileşenin normalize değerini ve nihai
    skoru/kategoriyi GeoJSON'a yazacak sütunlar olarak ekler.
    """
    data_raw = city_data_raw(config.city_id)
    output_path = city_data_proc(config.city_id) / "roads_with_hvi.geojson"
    if is_cache_valid(output_path, HVI_FORMULA_VERSION, force=force):
        print("roads_with_hvi.geojson güncel, atlanıyor")
        return gpd.read_file(output_path)

    adapter = load_population_adapter(config)
    population_paths = adapter.fetch_population_data(config)
    pbf_path = data_raw / f"{config.city_id}.osm.pbf"
    if not pbf_path.exists():
        pbf_path = data_raw / "aegean-latest.osm.pbf"  # İzmir eski dosya adı
    mahalle_gdf = adapter.build_neighborhood_layer(pbf_path, population_paths, config)

    roads = roads.copy()
    roads_utm = roads.to_crs(config.crs)
    roads["centroid"] = roads_utm.geometry.centroid.to_crs("EPSG:4326")
    road_pts = roads.set_geometry("centroid")[["centroid"]].set_geometry("centroid")
    road_pts.crs = roads.crs

    # "sosyoekonomik_skor" isteğe bağlıdır - her şehir adapter'ı güvenilir bir
    # sosyoekonomik gösterge bulamayabilir; bu durumda bileşen sessizce
    # dışarıda bırakılır, core kodu değişmez.
    has_sosyoekonomik = "sosyoekonomik_skor" in mahalle_gdf.columns
    optional_cols = ["sosyoekonomik_skor"] if has_sosyoekonomik else []
    mahalle_cols = mahalle_gdf[["mahalle_adi", "ilce_adi", "nufus_yogunlugu", "yasli_oran", "cocuk_oran",
                                 *optional_cols, "geometry"]]
    joined = gpd.sjoin(road_pts, mahalle_cols, how="left", predicate="within")
    roads["mahalle_adi"] = joined["mahalle_adi"].values
    roads["nufus_yogunlugu"] = joined["nufus_yogunlugu"].values
    roads["yasli_oran"] = joined["yasli_oran"].values
    roads["cocuk_oran"] = joined["cocuk_oran"].values
    if has_sosyoekonomik:
        roads["sosyoekonomik_skor"] = joined["sosyoekonomik_skor"].values

    # --- Sağlığa/yeşil alana uzaklık ve bina yoğunluğu: OSM'den, statik (yıldan bağımsız) ---
    print("Sağlık hizmeti noktaları yükleniyor...")
    health_points = load_health_points(config, pbf_path)
    print(f"  {len(health_points):,} sağlık noktası bulundu")
    print("Yeşil alan poligonları yükleniyor...")
    green_polys = load_green_space_polygons(config, pbf_path)
    print(f"  {len(green_polys):,} yeşil alan poligonu bulundu")
    print("Bina merkez noktaları yükleniyor (yoğunluk için)...")
    building_centroids = load_building_centroids(config, pbf_path)
    print(f"  {len(building_centroids):,} bina bulundu")

    centroid_utm = roads_utm.geometry.centroid
    roads["dist_saglik_m"] = _nearest_distance_m(centroid_utm, health_points, config.crs).round(1)
    roads["dist_yesil_m"] = _nearest_distance_m(centroid_utm, green_polys, config.crs).round(1)

    building_centroids_utm = building_centroids.to_crs(config.crs)
    print(f"Bina yoğunluğu hesaplanıyor ({BUILDING_DENSITY_BUFFER_M} m tampon)...")
    roads["bina_yogunlugu"] = _building_density_per_km2(building_centroids_utm, roads_utm).round(1)
    sifir_oran = (roads["bina_yogunlugu"] == 0).mean()
    print(f"  bina yoğunluğu 0 çıkan yol oranı: %{sifir_oran * 100:.1f}")
    if sifir_oran > 0.25:
        # Dar bir tampon mesafesi bu oranı yapay olarak şişirip geometrik
        # ortalama yüzünden tüm HVI sıralamasını bozabilir; erken uyar.
        print("  UYARI: bu oran beklenenden yüksek - tampon mesafesini "
              "veya OSM bina kapsamını kontrol edin")

    roads = roads.drop(columns=["centroid"])

    # --- Statik (yıldan bağımsız) bileşenlerin normalize değerleri ---
    roads["exposure_norm"] = normalize_0_1(roads["nufus_yogunlugu"])
    roads["sensitivity_yasli_norm"] = normalize_0_1(roads["yasli_oran"])
    roads["sensitivity_cocuk_norm"] = normalize_0_1(roads["cocuk_oran"])
    roads["sensitivity_saglik_norm"] = normalize_0_1(roads["dist_saglik_m"])
    roads["sensitivity_yesil_norm"] = normalize_0_1(roads["dist_yesil_m"])
    roads["sensitivity_yapilasma_norm"] = normalize_0_1(roads["bina_yogunlugu"])

    static_components = [
        "exposure_norm", "sensitivity_yasli_norm", "sensitivity_cocuk_norm",
        "sensitivity_saglik_norm", "sensitivity_yesil_norm", "sensitivity_yapilasma_norm",
    ]

    if has_sosyoekonomik:
        # Skor yüksek = ilçe daha gelişmiş = risk katkısı DÜŞÜK olmalı;
        # bu yüzden riske normalize edilirken skorun TERSİ kullanılır
        # (ağaç örtüsündeki NDVI tersleme deseniyle aynı mantık).
        roads["sensitivity_sosyoekonomik_norm"] = 1 - normalize_0_1(roads["sosyoekonomik_skor"])
        static_components.append("sensitivity_sosyoekonomik_norm")

    # --- Yıl bazlı bileşenler: ORTAK ölçekle normalize edilir ---
    # Sıcaklık ve NDVI her yıl kendi min-max aralığına sıkıştırılsaydı, aynı
    # sıcaklık iki yılda farklı bir risk katkısı üretir ve yıl karşılaştırması
    # anlamını yitirirdi. `core/roads.py` LST risk skorunda aynı gerekçeyle
    # ortak ölçek kullanıyor; burada o zincir korunuyor.
    risk_all = pd.concat([roads[f"risk_score_{y}"] for y in years])
    ndvi_all = pd.concat([roads[f"ndvi_mean_{y}"] for y in years])
    risk_min, risk_max = risk_all.min(), risk_all.max()
    ndvi_min, ndvi_max = ndvi_all.min(), ndvi_all.max()

    def _scale(series: pd.Series, lo: float, hi: float) -> pd.Series:
        return series * 0 if hi == lo else (series - lo) / (hi - lo)

    for year in years:
        # Ağaç örtüsü NDVI'nin TERSİ ile riske katkı sağlar: az ağaç = yüksek risk.
        roads[f"hazard_norm_{year}"] = _scale(roads[f"risk_score_{year}"], risk_min, risk_max)
        roads[f"sensitivity_agac_norm_{year}"] = 1 - _scale(roads[f"ndvi_mean_{year}"], ndvi_min, ndvi_max)

        year_components = [f"hazard_norm_{year}", f"sensitivity_agac_norm_{year}", *static_components]
        has_all_data = roads[year_components].notna().all(axis=1)

        # Bileşenler geometrik ortalamadan önce [0,1] yerine
        # [COMPONENT_FLOOR, 1] aralığına ölçeklenir. Gerekçe: min-max
        # normalizasyonda 0, "hiç risk yok" değil "veri kümesindeki en düşük
        # değer" demektir; log(0)'ı önlemek için eklenen çok küçük bir
        # epsilon ise bu 0'ı fiilen bir cezaya çevirir (1e-6 ile bir bileşenin
        # 0.0 mı 0.001 mi olduğu skoru iki katından fazla değiştiriyordu).
        # Taban değeri, "bir bileşen düşükse toplam risk de düşer" davranışını
        # korur ama etkisini sürekli ve sınırlı tutar.
        comp_matrix = roads.loc[has_all_data, year_components].to_numpy()
        comp_matrix = COMPONENT_FLOOR + (1 - COMPONENT_FLOOR) * comp_matrix
        geo_mean = np.exp(np.log(comp_matrix).mean(axis=1))
        roads.loc[has_all_data, f"hvi_score_{year}"] = geo_mean * 100
        roads.loc[~has_all_data, f"hvi_score_{year}"] = np.nan

    # --- Yüzde ve kategori: TÜM yılların ortak dağılımından ---
    # Her yıl kendi içinde 0-100'e ölçeklenseydi, tanım gereği her yılın en
    # kötü yolu %100 çıkar ve "2026'da risk arttı" demek imkansız olurdu.
    # Jenks sınırları da bir kez, birleşik dağılımdan hesaplanır; böylece
    # "Kritik" her iki yılda aynı eşiği ifade eder ve yolların yıllar arası
    # kategori değiştirmesi gerçek bir değişimi gösterir.
    score_all = pd.concat([roads[f"hvi_score_{y}"] for y in years]).dropna()
    score_min, score_max = score_all.min(), score_all.max()

    pct_all = _scale(score_all, score_min, score_max) * 100
    breaks = jenkspy.jenks_breaks(pct_all.to_numpy(), n_classes=5)
    print(f"Ortak Jenks sınırları (tüm yıllar): {[round(b, 1) for b in breaks]}")

    for year in years:
        gecerli = roads[f"hvi_score_{year}"].notna()
        roads.loc[gecerli, f"hvi_percentage_{year}"] = (
            _scale(roads.loc[gecerli, f"hvi_score_{year}"], score_min, score_max) * 100
        )
        roads.loc[gecerli, f"hvi_category_{year}"] = pd.cut(
            roads.loc[gecerli, f"hvi_percentage_{year}"], bins=breaks,
            labels=CATEGORY_ORDER_5, include_lowest=True,
        )
        print(f"[{year}] HVI dağılımı:\n{roads[f'hvi_category_{year}'].value_counts().sort_index()}")

        # Açıklanabilirlik: her bileşen için "yüksek/düşük" gibi doğal-dilde
        # etiket üretilir. Ağaç örtüsü etiketi kasıtlı olarak NDVI'nin
        # KENDİ yönünde (yüksek NDVI = "yüksek ağaç örtüsü") - risk
        # katkısındaki tersleme sadece skor hesabında, kullanıcıya gösterilen
        # metinde değil.
        roads.loc[gecerli, f"_label_sicaklik_{year}"] = bucket_5(
            roads.loc[gecerli, f"risk_score_{year}"], BUCKET_LABELS_5
        ).astype(str)
        roads.loc[gecerli, f"_label_agac_{year}"] = bucket_5(
            roads.loc[gecerli, f"ndvi_mean_{year}"], BUCKET_LABELS_5
        ).astype(str)

    roads["_label_nufus"] = bucket_5(roads["exposure_norm"], BUCKET_LABELS_5_DENSITY).astype(str)
    roads["_label_yasli"] = bucket_5(roads["sensitivity_yasli_norm"], BUCKET_LABELS_5).astype(str)
    roads["_label_cocuk"] = bucket_5(roads["sensitivity_cocuk_norm"], BUCKET_LABELS_5).astype(str)
    roads["_label_saglik"] = bucket_5(roads["sensitivity_saglik_norm"], BUCKET_LABELS_5_DISTANCE).astype(str)
    roads["_label_yesil"] = bucket_5(roads["sensitivity_yesil_norm"], BUCKET_LABELS_5_DISTANCE).astype(str)
    roads["_label_yapilasma"] = bucket_5(roads["sensitivity_yapilasma_norm"], BUCKET_LABELS_5_DENSITY).astype(str)
    if has_sosyoekonomik:
        # Etiket kasıtlı olarak skorun KENDİ yönünde ("yüksek" = gelişmiş
        # ilçe) - risk katkısındaki tersleme sadece skor hesabında.
        roads["_label_sosyoekonomik"] = bucket_5(normalize_0_1(roads["sosyoekonomik_skor"]), BUCKET_LABELS_5).astype(str)

    for year in years:
        roads[f"hvi_category_{year}"] = roads[f"hvi_category_{year}"].astype(str)

    roads.to_file(output_path, driver="GeoJSON")
    write_cache_meta(output_path, HVI_FORMULA_VERSION)
    print(f"Kaydedildi: {output_path.name} ({len(roads):,} yol segmenti)")
    return roads
