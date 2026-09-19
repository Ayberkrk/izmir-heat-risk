# Değişiklik Geçmişi

Bu dosya, pipeline'da ve desteklenen şehirlerde yapılan önemli
değişiklikleri sürüm sürüm listeler.

## v1.5.0 - 2026-09-19

- Repo `izmir-heat-risk` -> `turkiye-heat-risk` olarak yeniden
  adlandırıldı - artık tek şehre özel olmayan bir isim (üçüncü şehir bu
  sürümde eklendi). README/CI workflow'undaki hardcode repo adı
  referansları (badge URL'i, docker tag'i, klonlama komutu) güncellendi.
- Üçüncü şehir olarak **Şanlıurfa** eklendi (Haliliye + Eyyübiye +
  Karaköprü çekirdeği), Eskişehir'in TÜİK-statik-CSV şablonuyla - CKAN
  portalı olmayan HERHANGİ bir Türkiye şehri için şablonun tekrar
  kullanılabilir olduğunu kanıtlar. Nüfus (ADNKS 2025), yaşlı oranı
  (TÜİK 2025) ve SEGE-2022 skorları resmi kaynaklardan (bkz.
  `src/cities/sanliurfa/adapter.py` docstring'i - kaynaklar ve bilinen
  bir kapsam sınırlaması: il düzeyinde 0-14 yaş yayını bulunamadığı için
  TÜİK'in kendi 0-17 "çocuk nüfus" tanımı kullanıldı). bbox, idari ilçe
  sınırları yerine (Harran ovasına uzanan geniş kırsal alanı dışarıda
  bırakmak için) gerçek kentsel mahalle kümesi baz alınarak belirlendi.

## v1.4.0 - 2026-09-18

- Bozuk/eksik alanlı `config.yaml` dosyaları için anlaşılır hata
  mesajları üretildi (`core/city_config.py`) - önceden belirsiz bir
  `KeyError`/`TypeError` ile patlıyordu.

## v1.3.0 - 2026-09-17

- OSM centroid hesaplamasındaki gerçek bir CRS hatası düzeltildi:
  coğrafi (derece) CRS'te centroid almak büyük/simetrik olmayan
  poligonlarda merkezi sistematik kaydırıyordu (`osm_amenities.py`,
  `load_health_points`/`load_building_centroids`).
  Landsat sahne seçimine çoklu-sahne medyan kompozit eklendi (tek
  sahneye kıyasla tek-günlük anomalilerin etkisini azaltır).
  Dockerfile'a rasterio için eksik `libexpat1`/`libgomp1` sistem
  kütüphaneleri eklendi - CI'a eklenen yeni `docker` job'ının build
  sırasında yakaladığı ilk gerçek bug.
  `validate_city.py`'a adapter/EPSG doğrulaması eklendi, test kapsamı
  genişletildi.

## v1.2.0 - 2026-09-16

- CI eklendi (GitHub Actions, `pytest` job'ı). `map_builder.py` için
  test kapsamı genişletildi. Bağımlılıklara üst sınır (`requirements.txt`)
  ve İzmir'in eski `aegean-latest.osm.pbf` dosya adı için tekilleştirilmiş
  bir geriye dönük uyumluluk yolu eklendi.

## v1.1.0 - 2026-09-14

- `core/roads.py`, `core/text_utils.py` ve `core/osm_amenities.py` hiç
  test kapsamında değildi; ortak (yıl bazlı değil) min-max risk skoru
  ölçeklemesi, Türkçe karakter normalizasyonu ve OSM `other_tags`
  ayrıştırması için testler eklendi.

## v1.0.0 - 2026-09-12

İlk sürüm: uçtan uca çalışan pipeline (Landsat LST/NDVI -> OSM yol ağı ->
9 bileşenli geometrik ortalama Isı Hassasiyet Endeksi -> interaktif Folium
haritası), şehir bazlı mimari (`src/core/` şehirden bağımsız,
`src/cities/<sehir>/` izole), iki referans şehir (İzmir: CKAN tabanlı
adapter; Eskişehir: TÜİK-statik-CSV şablonu), sürüm damgalı önbellek
(`core/cache.py`), iki farklı harita çıktısı (çevrimdışı tek dosya +
GitHub Pages için fetch tabanlı bölünmüş sürüm), Landsat QA_PIXEL piksel
düzeyinde bulut maskesi ve ilk test paketi.
