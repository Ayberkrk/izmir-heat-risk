# Katkıda Bulunma: Yeni Bir Şehir Ekleme

Bu proje şehir bazlı bir mimariye sahiptir: `src/core/` altındaki kod
tamamen şehirden bağımsızdır, her şehrin kendi parametreleri ve nüfus veri
mantığı `src/cities/<sehir>/` altında izole edilir. Yeni bir şehir eklemek
`src/core/` içindeki hiçbir dosyayı değiştirmeyi gerektirmemelidir.

## Adımlar

### 1. `src/cities/<sehir>/` dizinini oluştur

```bash
mkdir -p src/cities/<sehir>
touch src/cities/<sehir>/__init__.py
```

`<sehir>` küçük harf, Türkçe karaktersiz, kısa bir kimlik olmalı (ör.
`ankara`, `antalya`) - bu kimlik `--city <sehir>` bayrağında ve
`src/cities/<sehir>/config.yaml` yolunda kullanılır.

### 2. `config.yaml`'ı doldur

`src/cities/izmir/config.yaml` dosyasını örnek al. Zorunlu alanlar:

```yaml
city:
  name: "Şehrin Görünen Adı"
  bbox: [batı, güney, doğu, kuzey]   # derece cinsinden
  crs: "EPSG:xxxxx"                   # şehrin bulunduğu UTM dilimi (metre cinsinden CRS)

landsat:
  max_cloud_cover: 30                 # % - gerekirse gevşet

osm:
  pbf_url: "https://download.geofabrik.de/... veya https://download.openstreetmap.fr/..."
  admin_level_ilce: <sayı>            # OSM admin_level - ülkeden ülkeye değişir
  admin_level_mahalle: <sayı>
  highway_types: [...]                # hangi yol tiplerinin analize dahil edileceği

roads:
  buffer_meters: 10

population:
  adapter: "cities.<sehir>.adapter"   # aşağıdaki adım 3
  # Adapter'ının ihtiyaç duyduğu ek anahtarları buraya ekleyebilirsin
  # (CKAN dataset ID'leri, dosya yolları, API anahtarları vb.)
```

`admin_level_ilce`/`admin_level_mahalle` değerlerini önceden doğrulamak
için:

```python
import geopandas as gpd
gdf = gpd.read_file("<pbf-dosyasi>", layer="multipolygons", bbox=(batı, güney, doğu, kuzey))
print(sorted(gdf[gdf["boundary"] == "administrative"]["admin_level"].dropna().unique()))
```

### 3. Nüfus/demografi veri kaynağını belirt ve adapter'ı yaz

`src/core/hvi.py`, nüfus yoğunluğu, yaşlı oranı ve çocuk oranını
`mahalle_gdf` üzerinden okur. Bu veri şehirden şehre çok farklı
biçimlerde geldiği için (CKAN, TÜİK, Eurostat, ulusal istatistik
kurumu API'si...) genel bir şema zorlanmaz; bunun yerine her şehir kendi
**adapter**'ını yazar.

`src/cities/<sehir>/adapter.py` şu iki fonksiyonu uygulamalıdır:

```python
def fetch_population_data(config: CityConfig) -> dict[str, Path]:
    """Nüfus/demografi kaynaklarını indirir (zaten indirilmişse atlar) ve
    yerel dosya yollarını döndürür."""

def build_neighborhood_layer(pbf_path: Path, population_paths: dict[str, Path],
                              config: CityConfig) -> gpd.GeoDataFrame:
    """Mahalle sınırlarını nüfus verileriyle zenginleştirir. Dönen
    GeoDataFrame en az şu sütunları içermelidir:
      - mahalle_adi, ilce_adi, geometry
      - nufus_yogunlugu   (kişi/km²)
      - yasli_oran        (0-1 arası kesir, 65+ nüfus oranı)
      - cocuk_oran        (0-1 arası kesir, 0-14 nüfus oranı)

    İsteğe bağlı: `sosyoekonomik_skor` sütununu da eklersen (yüksek = daha
    gelişmiş/az kırılgan), HVI bunu dokuzuncu bir bileşen olarak otomatik
    kullanır - `src/core/hvi.py` bu sütunun var olup olmadığını kontrol
    eder, eklemesen de pipeline hatasız çalışır.
    """
```

`src/cities/izmir/adapter.py` referans bir örnektir - CKAN'dan CSV çekme,
Türkçe karakter normalizasyonu, konumsal (isme göre değil) mahalle-ilçe
eşlemesi ve resmi bir raporu (SEGE-2022) küçük bir referans CSV olarak
repoya gömme gibi desenleri gösterir. Farklı bir veri kaynağı biçimin
varsa (ör. GeoJSON, doğrudan bir API) sadece bu iki fonksiyonun imzasına
uymak yeterlidir - CKAN'a özel hiçbir şey zorunlu değildir.

Ham/işlenmiş veri (`data/raw/<sehir>/`, `data/processed/<sehir>/`) şehir
kimliğine göre otomatik ayrılır - bu konuda adapter'ında hiçbir şey
yapmana gerek yok, `src/core/paths.py` bunu senin için halleder.

### 4. Doğrulama scriptini çalıştır

```bash
python validate_city.py <sehir>
```

Bu, hiçbir veri indirmeden/işlemeden şunları kontrol eder:
- `config.yaml`'ın gerekli tüm alanları içerdiğini
- `bbox`'ın geçerli bir koordinat aralığı olduğunu
- Adapter modülünün import edilebildiğini ve iki fonksiyonu da
  uyguladığını
- OSM pbf URL'inin ve (varsa) CKAN tabanlı nüfus kaynağının gerçekten
  erişilebilir olduğunu

Hata varsa script bunları listeleyip çıkış kodu 1 ile sonlanır.

### 5. Uçtan uca çalıştır

```bash
python pipeline.py --city <sehir> --years <yıl1> <yıl2>
```

İlk çalıştırma Landsat sahnelerini ve OSM özütünü indirir - internet
bağlantısına göre 15-25 dakika ve birkaç GB disk alanı gerektirebilir.
Script kesintiye uğrarsa aynı komutla kaldığı yerden devam eder.

### 6. Pull request aç

Değişikliklerini bir dala (branch) taşı, PR açarken şunları belirt:
- Hangi şehir eklendi, bbox ve veri kaynağı ne
- `validate_city.py <sehir>` ve `pipeline.py --city <sehir>` çıktısının
  başarıyla tamamlandığını (loglardan kısa bir alıntı yeterli)
- Nüfus verisinin lisansı/kullanım şartları (açık veri portalı, TÜİK vb.)

## Yeni şehir talebi (kod yazmadan)

Kendin katkı sağlamak istemiyor ama bir şehrin eklenmesini istiyorsan,
`.github/ISSUE_TEMPLATE/` altındaki "Yeni şehir talebi" şablonuyla bir
issue aç.
