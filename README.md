# Kentsel Isı Adası ve Isı Hassasiyet Endeksi (HVI)

## English summary

An open-data, reproducible urban heat risk pipeline. It combines Landsat
land surface temperature (LST), the OpenStreetMap road network, and
demographic data into a street-level, explainable Heat Vulnerability Index
(HVI): Landsat LST/NDVI, a road-to-temperature spatial join, a 9-component
geometric-mean HVI (temperature, tree canopy, population density,
elderly/child population share, distance to hospital/pharmacy, distance to
green space, built-up density), and pixel-level Jenks natural-breaks
categorization shared across years. The architecture is city-agnostic -
`src/core/` never changes when a new city is added; Izmir and Eskişehir are
the two supported examples today (see [CONTRIBUTING.md](CONTRIBUTING.md) to
add another).

Quick start (produces a single-file interactive HTML map):

```bash
python pipeline.py --city izmir --years 2020 2026 --main-year 2026 --open
```

The rest of this README - methodology, findings, setup, project layout,
known limitations - is in Turkish (this is an Izmir/Türkiye-focused
project). Machine translation works well if you want the full detail; the
summary above and the code/docstrings should be enough to navigate the
repository.

---

Açık verilerle çalışan, tekrar üretilebilir bir kentsel ısı riski analiz hattı.
Landsat yüzey sıcaklığı, OpenStreetMap yol ağı ve demografik verileri
birleştirerek ısı riskini sokak ölçeğinde haritalar. Şehirden bağımsız bir
mimariye sahiptir; İzmir ve Eskişehir şu an desteklenen iki örnek, yeni bir
şehir eklemek `src/core/` içindeki hiçbir dosyayı değiştirmeden mümkündür
(bkz. [CONTRIBUTING.md](CONTRIBUTING.md)).

**Canlı harita:** GitHub Pages'te barındırılan, veri talep üzerine yüklenen
küçük sürüm için `docs/index.html` (Pages etkinleştirildiğinde bir URL'e
dönüşür). Tamamen çevrimdışı, tek dosyalık sürüm (~60 MB, GitHub'ın 50 MB
uyarı/100 MB ret sınırını aştığı için depoda tutulmuyor) aşağıdaki komutla
birkaç dakikada yerelde üretilir:

```bash
python pipeline.py --city izmir --years 2020 2026 --main-year 2026 --open
```

![İzmir HVI interaktif haritası: yol ağı Isı Hassasiyet Endeksi'ne göre turuncudan bordoya renklendirilmiş, sağ üstte katman kontrolü, sol altta yıl seçici ve gösterge](assets/screenshots/harita-genel.png)

## İçindekiler

- [Ne yapıyor?](#ne-yapıyor)
- [Başka bir şehre/bölgeye uyarlama](#başka-bir-şehrebölgeye-uyarlama)
- [Metodoloji](#metodoloji)
- [2020 → 2026: Bulgular](#2020--2026-bulgular)
- [Kurulum ve çalıştırma](#kurulum-ve-çalıştırma)
- [Proje yapısı](#proje-yapısı)
- [Bilinen sınırlamalar](#bilinen-sınırlamalar)

## Ne yapıyor?

1. **Uydu verisi** - Landsat 8/9 (Microsoft Planetary Computer) üzerinden
   İzmir büyükşehir alanını kaplayan en az bulutlu yaz sahnelerini indirir.
2. **Yüzey sıcaklığı (LST) ve NDVI** - termal banttan gerçek yüzey
   sıcaklığını (°C), kırmızı/yakın-kızılötesi banttan bitki örtüsü
   yoğunluğunu hesaplar; sahneleri tek bir kesintisiz mozaikte birleştirir.
3. **Yol ağı ↔ sıcaklık eşlemesi** - OpenStreetMap'ten çekilen ~44.000 yol
   segmentinin her birine, 10 metrelik bir tampon içindeki ortalama LST'yi
   atar ve 0-100 arası bir "risk skoru"na çevirir.
4. **Isı Hassasiyet Endeksi (HVI)** - sıcaklık, ağaç örtüsü, nüfus
   yoğunluğu, yaşlı/çocuk nüfus oranı, hastane/eczaneye uzaklık, yeşil
   alana uzaklık ve yapılaşma yoğunluğunu tek bir 0-100 skorda birleştirir;
   "burası hem sıcak hem kalabalık/yaşlı/çocuk nüfuslu hem de ağaçsız ve
   sağlık hizmetine uzak, yani gerçek risk burada" sorusuna cevap verir.
   Her bileşenin kendi değeri de ayrı ayrı saklanır - nihai skor tek başına
   değil, onu oluşturan etkenlerle birlikte görünür (bkz. Metodoloji).
5. **İnteraktif harita** - kategori bazlı aç/kapa katmanları, 2020/2026
   yıl seçici ve her yola tıklandığında skoru oluşturan tüm bileşenleri
   gösteren bir tooltip içeren, tarayıcıda tek dosya olarak açılabilen bir
   Folium/Leaflet haritası üretir.

## Başka bir şehre/bölgeye uyarlama

Proje artık şehir bazlı bir mimariye sahip: `src/core/` altındaki kod
tamamen şehirden bağımsızdır, İzmir'e özel her şey
`src/cities/izmir/config.yaml` ve `src/cities/izmir/adapter.py` içinde
izole edilmiştir. Yeni bir şehir eklemek `src/core/` içindeki
sabitleri değiştirmeyi **gerektirmez** - adım adım süreç için
[CONTRIBUTING.md](CONTRIBUTING.md)'ye bakın. Özetle:

**1. `src/cities/<sehir>/config.yaml` oluştur**
`bbox` (derece cinsinden [batı, güney, doğu, kuzey]), hedef UTM `crs`'i,
OSM `.osm.pbf` özüt URL'i ([openstreetmap.fr](https://download.openstreetmap.fr/extracts/)
veya [Geofabrik](https://download.geofabrik.de/)), `admin_level_ilce` /
`admin_level_mahalle` (bu etiket ülkeden ülkeye değişir - kendi bölgende
`osm_gdf['admin_level'].unique()` ile önceden doğrula) buraya yazılır.

**2. Bir demografi "adapter"ı yaz (en fazla emek isteyen adım)**
İki referans örnek farklı veri kaynağı senaryolarını gösterir:
  - `src/cities/izmir/adapter.py`: belediyenin kendi CKAN tabanlı açık veri
    portalı varsa (`acikveri.bizizmir.com`), mahalle seviyesinde nüfus/yaş.
  - `src/cities/eskisehir/adapter.py`: böyle bir portal YOKSA, TÜİK'in
    herkese açık ilçe seviyesindeki ADNKS yayınlarını statik CSV olarak
    kullanan şablon - kendi CKAN'ı olmayan başka bir Türkiye şehri için
    neredeyse değişiklik yapmadan uyarlanabilir.

Her iki örnek de `fetch_population_data()` / `build_neighborhood_layer()`
arayüzünü uygular. Yeni bir şehir için aynı arayüzü uygulayan kendi
adapter'ını `src/cities/<sehir>/adapter.py` altında yaz:
  - Mahalle/idari sınır poligonlarını OSM'den çekmeye devam edebilirsin.
  - Nüfus yoğunluğu, yaşlı ve çocuk nüfus oranı verisini yerel istatistik
    kurumundan (TÜİK, Eurostat, US Census vb.) veya belediyenin kendi açık
    veri portalından CSV/JSON olarak al.
  - Mahalle-ilçe eşlemesi her iki adapter'da da **isme göre değil konumsal
    sorguyla** (`sjoin`, centroid içinde mi) yapılıyor - aynı isimli
    mahallelerin yanlış ilçeyle eşleşmesini önlüyor. Bu yaklaşımı koru,
    hangi ülkede olursan ol işe yarar.

**3. Doğrula ve çalıştır**
```bash
python validate_city.py <sehir>
python pipeline.py --city <sehir> --years <yıllar>
```
`validate_city.py`, config.yaml'ın gerekli alanları içerdiğini, bbox'ın
geçerli olduğunu, adapter'ın import edilebildiğini ve veri kaynağı
URL'lerinin erişilebilir olduğunu indirmeden önce kontrol eder.

**4. HVI bileşenlerini değiştir**
`src/core/hvi.py` içindeki bileşen listesi (hazard, exposure, sensitivity_*)
ve bunların geometrik ortalamayla birleşimi genel bir yapıdadır - yeni bir
bileşen eklemek için mevcut normalize-et-birleştir desenini izle.

## Metodoloji

### Yüzey sıcaklığı (LST)

Landsat Collection 2 Level-2 ürünleri, termal bandı laboratuvarda zaten
Kelvin cinsinden yüzey sıcaklığına kalibre eder. Tek gereken ölçek dönüşümü:

```
LST(K) = piksel_değeri × 0.00341802 + 149.0
LST(°C) = LST(K) - 273.15
```

Bulutlar kızılötesiyi bozduğu için her sahne aranırken bulut oranı %30'un
altında tutulur ve her uydu karosu (path/row) için mevcut en temiz tarih
seçilir.

Sahne düzeyindeki düşük bulut oranı tek başına yeterli değil: toplam bulut
oranı düşük bir sahnede bile bulutun küçük bir kısmı doğrudan çalışma
alanının üzerine düşebilir. Bu yüzden `QA_PIXEL` bandı da indirilip LST ve
NDVI hesaplanmadan önce, sahnenin kendi piksel ızgarasında (mozaikleme ve
yeniden izdüşürmeden önce) piksel düzeyinde bir bulut maskesi uygulanır:
fill, dilated cloud, cirrus, cloud, cloud shadow ve snow bayraklarından
herhangi biri taşıyan pikseller `NaN`/nodata yapılır (`core/raster.py`,
`qa_invalid_mask`).

**UTM dilim sınırındaki şehirler:** USGS her Landsat sahnesini kendi
merkezine en yakın UTM dilimine işler. Bir şehrin bbox'ı iki komşu path/row
karosunun kesiştiği ve bu karoların farklı UTM dilimlerine düştüğü bir
noktaya denk gelirse (Eskişehir'de yaşandı: 4 karodan 3'ü UTM 36N/EPSG:32636,
biri UTM 35N/EPSG:32635), mozaikleme öncesi tüm sahneler `config.crs`'e
yeniden izdüşürülür (`core/raster.py`, `reproject_to_crs`) - aksi halde
`stream_mosaic` farklı dilimdeki sahneyi (aynı sayısal koordinatlar farklı
coğrafi konuma karşılık geldiği için) yanlış yere yapıştırır ve o bölgede
neredeyse hiç geçerli piksel kalmaz.

### Yol ↔ sıcaklık eşlemesi (spatial join)

Yollar çizgi geometrisi olduğu için doğrudan piksel ortalaması alınamaz;
her yola 10 metrelik bir tampon (buffer) verilip bu koridorun içine düşen
piksellerin **ortalaması** (aykırı değerlere karşı `mean`, `max`'tan daha
dayanıklı) `rasterstats.zonal_stats` ile hesaplanır. Sonuç, tüm yolların
ortak min-max aralığına göre 0-100'e normalize edilerek "risk skoru"na
çevrilir.

### Isı Hassasiyet Endeksi (HVI): çok bileşenli ve açıklanabilir

HVI artık dokuz bileşenin **geometrik ortalamasının** 100 ile ölçeklenmiş
hali:

```
HVI = geometrik_ortalama(Tehlike, Maruziyet, 7× Hassasiyet bileşeni) × 100
```

| Bileşen | Ne ölçer | Kaynak |
|---|---|---|
| Tehlike | LST risk skoru (yıl bazlı) | Landsat termal bant |
| Maruziyet | Nüfus yoğunluğu | İzmir B.Ş.B. açık veri |
| Hassasiyet - yaşlı oranı | 65+ nüfus oranı (ilçe) | İzmir B.Ş.B. açık veri |
| Hassasiyet - çocuk oranı | 0-14 nüfus oranı (ilçe) | İzmir B.Ş.B. açık veri (aynı CSV) |
| Hassasiyet - ağaç örtüsü | Yol tamponundaki ortalama NDVI'nin tersi | Landsat NDVI (zaten hesaplanıyor) |
| Hassasiyet - sağlık erişimi | En yakın hastane/klinik/eczaneye uzaklık | OSM (`amenity=hospital/clinic/pharmacy`) |
| Hassasiyet - yeşil alan erişimi | En yakın park/orman/çayır poligonuna uzaklık | OSM (`leisure=park`, `landuse=forest` vb.) |
| Hassasiyet - yapılaşma yoğunluğu | Yolun 150 m çevresindeki bina yoğunluğu | OSM bina (`building`) katmanı |
| Hassasiyet - sosyoekonomik gelişmişlik | İlçe bazlı SEGE-2022 gelişmişlik skorunun tersi | T.C. Sanayi ve Teknoloji Bakanlığı, resmi SEGE-2022 raporu |

Her bileşen önce kendi min-max aralığında 0-1'e normalize edilir (aksi
halde binlerce kişi/km² olan nüfus yoğunluğu, 0-1 arası bir kesir olan
yaşlı oranını eziyor). Eski sürümdeki üç bileşenli çarpım (`Tehlike ×
Maruziyet × Hassasiyet`) ile geometrik ortalama aynı sayıyı vermez, ama
yolları aynı sırayla dizer (biri diğerinin küpüdür); geometrik ortalama
bu sıralamayı keyfi sayıda bileşene genelleştirir ve "bir bileşen sıfıra
yakınsa toplam risk de düşük çıkar" özelliğini korur - ağırlıklı
aritmetik ortalama bunu sağlamaz.

Bu özelliğin bir yan etkisi var ve iki yerde ele alınıyor. Min-max
normalizasyonda 0, "hiç risk yok" değil "veri kümesindeki en düşük değer"
demektir; geometrik ortalama alınırken bu 0 tek başına tüm skoru
sıfırlayacağı için bileşenler önce `[0,05, 1]` aralığına ölçeklenir.
Böylece "bir bileşen düşükse toplam risk de düşer" davranışı korunur ama
tek bir bileşen skoru tamamen ele geçiremez.

**İki yıl karşılaştırılabilir:** HVI yüzdesi ve Jenks kategori sınırları
her yıl ayrı ayrı değil, tüm yılların **ortak** dağılımından hesaplanır.
Her yıl kendi içinde 0-100'e ölçeklenseydi tanım gereği her yılın en kötü
yolu %100 çıkar ve "2026'da risk arttı" demek mümkün olmazdı. LST risk
skorunda uygulanan ortak ölçek mantığı HVI'de de sürdürülür.

**Etiketler yüzdelik dilime göre:** haritadaki "yüksek / orta / çok yakın"
gibi etiketler eşit genişlikte aralıklara değil, sıralamaya (yüzdelik
dilim) göre üretilir. Eşit aralık kullanıldığında birkaç uç değer tüm
skalayı ele geçiriyor ve yolların %91'i "hastaneye çok yakın" çıkıyordu;
şimdi her etiket yolların yaklaşık beşte birine denk geliyor.

**Açıklanabilirlik:** nihai HVI skorunun yanında her bileşenin kendi
normalize değeri de GeoJSON'a yazılır (`hazard_norm_<yıl>`,
`exposure_norm`, `sensitivity_*_norm` sütunları) ve haritadaki tooltip'te
"Sıcaklık: yüksek, Ağaç örtüsü: çok düşük, Hastaneye uzaklık: uzak..."
şeklinde okunabilir etiketlere çevrilir - bir yolun HVI'sinin neden
yüksek/düşük olduğu haritadan doğrudan görülebilir.

Yaş dağılımı verisi sadece **ilçe** seviyesinde mevcut olduğu için, bir
ilçenin yaşlı/çocuk oranı o ilçenin tüm mahallelerine aynı şekilde
uygulanır (downscaling) - ilçe-içi ince farkları gözden kaçırır ama kaba
veriyle çalışırken standart ve dürüst bir yaklaşımdır.

**Sosyoekonomik bileşen:** İzmir B.Ş.B. açık veri portalında ve TÜİK'te
mahalle/ilçe seviyesinde güncel, güvenilir bir eğitim/gelir göstergesi
bulunamadı; onun yerine T.C. Sanayi ve Teknoloji Bakanlığı'nın resmi
**"İlçelerin Sosyo-Ekonomik Gelişmişlik Sıralaması Araştırması
(SEGE-2022)"** raporundaki ilçe bazlı gelişmişlik skoru kullanıldı - bu,
81 ilin tüm ilçelerini 56 değişkenle (demografi, istihdam, eğitim, sağlık,
finans, rekabetçilik, yaşam kalitesi) kapsayan, kamuya açık, tek seferlik
yayımlanmış resmi bir araştırma. Bu yüzden CKAN'dan indirilmek yerine
`src/cities/izmir/sege_2022_ilce.csv` olarak küçük bir referans dosyası
halinde repoya dahil edildi (bkz. `cities/izmir/adapter.py`). Bu bileşen
**isteğe bağlıdır** - başka bir şehrin adapter'ı bu veriyi sağlamazsa HVI
kalan sekiz bileşenle hesaplanmaya devam eder.

**Bu HVI, kapsamlı bir sağlık veya sosyoekonomik kırılganlık modeli değil;
mevcut açık verilerle oluşturulmuş, çok bileşenli bir önceliklendirme
endeksidir.**

### Kategorilere ayırma: neden Jenks doğal kırılım?

HVI skorları üç 0-1 kesirin çarpımı olduğu için dağılım sağa çarpık -
çoğu yol düşük skorda toplanır, az sayıda yol çok yüksek skora sıçrar.
İlk denemede `pd.qcut` (her kategoriye eşit sayıda yol) kullanıldı ama bu,
verideki gerçek yapıyı değil, zorla eşit dağıtılmış bir bölünmeyi
yansıtıyordu. **Jenks doğal kırılım** (`jenkspy`) bunun yerine grup-içi
varyansı minimize edip gruplar-arası varyansı maksimize eden sınırları
matematiksel olarak bulur - yani "doğada var olan" kümelenme noktalarını
tespit eder, kategorilere zorla eşit yol sayısı dağıtmaz. Jenks sınırları
2020 ve 2026 için ayrı ayrı değil, iki yılın **ortak** dağılımından bir
kez hesaplanır; böylece "Kritik" her iki yılda aynı eşiği ifade eder ve
bir yolun yıllar arasında kategori değiştirmesi gerçek bir değişimi
gösterir.

(Bu, tooltip'teki "yüksek / çok yakın" gibi bileşen etiketlerinden ayrı
bir karardır: **kategoriler** Jenks ile, **etiketler** yüzdelik dilimle
üretilir. Kategorilerde amaç verideki gerçek kümelenmeyi bulmak,
etiketlerde ise okuyucuya "bu yol diğerlerine göre nerede duruyor"
sorusunun cevabını vermek.)

### Zaman serisi: 2020 vs 2026 neden "ortak" normalize ediliyor?

Risk skorunu her yıl kendi min-max'ıyla normalize edersen, "2020'de 45°C"
ile "2026'da 45°C" farklı skorlara denk gelir - karşılaştırma anlamsızlaşır.
Bunun yerine iki yılın LST değerleri birleştirilip **tek bir ortak
min-max aralığı** bulunur, her iki yıl da bu aynı cetvelle ölçülür.

### Gece ısı adası (isteğe bağlı, `--night-lst`)

Landsat'ın termal bandı gündüz geçişi için tasarlanmıştır; gece ısı adası
etkisi (şehir merkezlerinin kırsala göre geceleri daha yavaş soğuması,
genelde gündüzden daha güçlü hissedilen bir etki) bu veri setinde yoktu.
`--night-lst` bayrağı, aynı Planetary Computer altyapısından MODIS'in
"LST_Night_1km" ürününü çeker (yazın tüm 8 günlük kompozitlerinin
piksel bazlı ortalaması, tek bir bulutlu gecenin sonucu domine etmesini
önlemek için). MODIS 1 km çözünürlükte olduğu için (Landsat'ın 30 m'sinin
aksine) bu katman yol segmenti değil **mahalle** ölçeğinde sunulur ve
HVI skoruna dahil edilmez - haritada ayrı, varsayılan olarak kapalı bir
katmandır.

## 2020 → 2026: Bulgular

*(6 yıllık pencere; her iki yıl da temmuz-ağustos Landsat sahnelerinden.
Aşağıdaki sayılar haritanın da beslendiği aynı veri setinden -
`data/processed/izmir/roads_timeseries.geojson` ve
`data/processed/izmir/roads_with_hvi.geojson`.)*

**Sıcaklık - genel eğilim:**
- 43.999 yol segmentinin ortalama sıcaklık değişimi: **+3.29 °C**
- En çok ısınan yol: **+14.0 °C** · en çok soğuyan yol: **-6.2 °C**
- Yolların **%98'i (43.045 / 43.999)** ısınma yönünde değişti; sadece
  43 yol soğudu, 911 yol pratik olarak değişmedi.
- Yolların **%63'ü** "belirgin ısındı" (+3°C ve üzeri) kategorisinde.

**HVI - risk dağılımı (dokuz bileşenli metodoloji, 5 kategori, iki yılın
ortak Jenks sınırlarıyla):**

| Kategori | 2020 | 2026 | Değişim |
|---|---|---|---|
| Düşük | 8.370 | 6.570 | -1.800 |
| Orta | 13.350 | 12.535 | -815 |
| Yüksek | 10.596 | 11.199 | +603 |
| Kritik | 7.531 | 8.626 | +1.095 |
| Aşırı Kritik | 3.294 | 4.211 | +917 |

Kategori sınırları iki yılın ortak dağılımından bir kez hesaplandığı için
"Kritik" her iki yılda aynı eşiği ifade eder; yani yukarıdaki değişim
sütunu gerçek bir kayma gösteriyor. Düşük risk grubundan çıkan yollar üst
kategorilere geçmiş durumda: 2026'da Kritik ve Aşırı Kritik segment sayısı
2020'ye göre **%18 artmış**.

> Not: bu sayılar deponun daha eski sürümlerindekilerden farklı. HVI
> metodolojisi iki kez değişti: önce üç bileşenden dokuz bileşene geçildi,
> sonra yapılaşma yoğunluğu bileşenindeki bir hesap hatası düzeltildi ve
> yıllar ortak ölçeğe alındı. Eski sayılar bu düzeltmelerden önceki
> hallerdir.

**En yüksek ortalama HVI'ye sahip 5 mahalle (2026, en az 20 yol segmenti
olan mahalleler arasından):**

1. Umut Mahallesi - %91,1
2. İhsan Alyanak Mahallesi - %90,0
3. Bozyaka Mahallesi - %88,2
4. Abdi İpekçi Mahallesi - %87,2
5. Sarıyer Mahallesi - %86,9

Listenin tamamı Karabağlar ve Konak'ın yüksek yoğunluklu, düşük gelirli,
ağaç örtüsü zayıf mahallelerinden oluşuyor - modelin sıcaklık, yapılaşma,
ağaç örtüsü ve sosyoekonomik boyutu birlikte değerlendirdiğinde beklenen
sonuç.

**Ne yapılabilir?** Bu bulgular şunu öneriyor:
- Kritik/Aşırı Kritik kategorisindeki 12.837 yol segmenti (toplamın
  ~%29'u) ağaçlandırma, gölgelendirme, geçirgen/açık renk asfalt gibi
  somut müdahaleler için önceliklendirilebilir.
- Bir yolun HVI'si artık haritadaki tooltip'ten "neden" sorusuyla birlikte
  okunabiliyor - ör. bir yol hem sıcak hem ağaçsız hem hastaneye uzaksa,
  bu üç ayrı müdahale türünü (gölgelendirme, sağlık erişimi planlaması,
  acil durum hazırlığı) aynı anda işaret eder.
- İzlemenin sürdürülmesi öneriliyor - `--years` parametresiyle gelecek
  yıllar kolayca eklenebilir.

**Metodolojik uyarı:** 2020 ve 2026 için seçilen yaz Landsat sahneleri
arasında yol segmentleri boyunca ortalama +3.29°C LST farkı gözlenmiştir.
Bu değer uzun dönem iklim trendi olarak yorumlanmamalıdır; sahne tarihi,
meteorolojik koşullar, toprak nemi ve dönemsel sıcaklık farkları sonucu
etkileyebilir. Daha güvenilir trend analizi için çoklu yaz sahnelerinden
yıllık kompozitlerin kullanılması planlanmaktadır.

## Kurulum ve çalıştırma

```bash
git clone <bu-repo>
cd izmir-heat-risk
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Tüm hattı (indirme → LST/NDVI → yol eşleme → HVI → harita) çalıştırmak için:

```bash
python pipeline.py --city izmir --years 2020 2026 --main-year 2026 --open
```

- `--city`: `src/cities/<sehir>/config.yaml` içindeki şehir kimliği (varsayılan: `izmir`)
- `--years`: karşılaştırılacak yıllar (2 veya daha fazla olabilir)
- `--main-year`: hangi yılın "ana/düz" klasör yapısını kullanacağı
  (`data/raw/<sehir>/...` vs. `data/raw/<sehir>/<yıl>/...`)
- `--open`: harita üretildikten sonra otomatik tarayıcıda aç
- `--force`: yol risk skoru ve HVI önbelleğini yok say, yeniden hesapla
- `--night-lst`: mahalle ölçeğinde MODIS gece ısı adası katmanını da üret
  (isteğe bağlı, ek bir uydu kaynağı indirir - bkz. Metodoloji)

Her adım, çıktısı zaten diskte varsa atlanır - script yarıda kesilse bile
`python pipeline.py --city izmir` ile kaldığı yerden devam eder. İlk
çalıştırma (4 Landsat sahnesi × 2 yıl + OSM özütü) makul bir internet
bağlantısında ~15-25 dakika ve ~5-6 GB disk alanı gerektirir.

Yol risk skoru ve HVI çıktıları formül sürümü değiştiğinde otomatik
olarak yeniden hesaplanır (bkz. `src/core/cache.py`); veri kaynağı aynı
kalıp sadece parametre denemek isteniyorsa `--force` ile elle de
zorlanabilir.

## Testler

Saf/mantık ağırlıklı fonksiyonlar (normalizasyon, yüzdelik dilim
etiketleme, config doğrulama, önbellek geçerliliği) için birim testler
`tests/` altında yer alır - uydu indirme veya OSM ağı gerektirmez, saniyeler
içinde çalışır:

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

## Docker ile çalıştırma

`rasterio`/GDAL kurulumu makineden makineye (özellikle Windows'ta) sorun
çıkarabiliyor - `Dockerfile`, "bu imaj çalışıyorsa senin makinende de
çalışır" garantisi verir. Çıktılar (`data/`, `output/`, `docs/`) konteyner
dışında kalıcı olsun diye host'a mount edilir:

```bash
docker build -t izmir-heat-risk .
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/docs:/app/docs" \
  izmir-heat-risk --city izmir --years 2020 2026 --main-year 2026
```

## Barındırma (GitHub Pages)

`pipeline.py`, her şehir için iki harita üretir (bkz. `core/map_builder.py`):
`output/<sehir>_hvi_map.html` (tek dosya, çevrimdışı) ve `docs/<sehir>/`
(veri ayrı küçük GeoJSON dosyalarına bölünmüş, tarayıcı sadece açılan
katmanı indirir - ilk sayfa yükü birkaç yüz KB). İkincisini yayınlamak için:

1. En az bir şehir için `python pipeline.py --city <sehir>` çalıştır.
2. `python build_docs_index.py` ile şehirler arası karşılaştırma sayfasını
   (`docs/index.html`) üret.
3. `docs/` klasörünü commit'le, GitHub'da Settings → Pages → Branch: `main`,
   klasör: `/docs` seç.

## Proje yapısı

```
izmir-heat-risk/
├── pipeline.py               # Tek üst seviye giriş noktası: python pipeline.py --city izmir
├── validate_city.py           # Yeni bir şehir config.yaml'ını hızlıca doğrular
├── build_docs_index.py        # docs/ altındaki şehirler için karşılaştırma sayfası üretir
├── src/
│   ├── core/                  # Şehirden bağımsız, genel pipeline mantığı
│   │   ├── city_config.py     #   config.yaml yükleyici + doğrulama
│   │   ├── satellite.py       #   Landsat indirme
│   │   ├── raster.py          #   LST/NDVI hesaplama + bellek-güvenli mozaikleme
│   │   ├── roads.py           #   OSM yol ağı + yıllık sıcaklık/NDVI eşleme
│   │   ├── osm_amenities.py   #   sağlık/yeşil alan/bina katmanları (OSM'den)
│   │   ├── hvi.py             #   çok bileşenli HVI hesaplama
│   │   ├── map_builder.py     #   interaktif Folium haritası (çevrimdışı + barındırma sürümü)
│   │   ├── night_lst.py       #   isteğe bağlı: mahalle ölçeğinde MODIS gece ısı adası katmanı
│   │   ├── cache.py           #   ara çıktılar için sürüm damgalı önbellek geçerliliği
│   │   └── text_utils.py      #   şehirler arası paylaşılan Türkçe metin normalizasyonu
│   └── cities/
│       ├── izmir/
│       │   ├── config.yaml         #   İzmir'e özel bbox, URL'ler, sütun eşlemeleri
│       │   ├── adapter.py          #   İzmir'e özel nüfus/demografi mantığı (CKAN)
│       │   └── sege_2022_ilce.csv  #   İlçe bazlı sosyoekonomik gelişmişlik skoru (resmi SEGE-2022)
│       └── eskisehir/
│           ├── config.yaml         #   Eskişehir'e özel bbox, URL'ler
│           ├── adapter.py          #   TÜİK tabanlı nüfus/demografi mantığı (CKAN'sız şablon)
│           ├── ilce_nufus.csv      #   İlçe nüfusu + yaşlı/çocuk oranı (TÜİK ADNKS 2025)
│           └── sege_2022_ilce.csv  #   İlçe bazlı sosyoekonomik gelişmişlik skoru (resmi SEGE-2022)
├── tests/                     # Saf/mantık fonksiyonları için birim testler (ağ gerektirmez)
├── docs/                      # GitHub Pages'in servis ettiği, küçük/fetch tabanlı harita sürümü
│   ├── index.html             #   şehirler arası karşılaştırma sayfası (build_docs_index.py üretir)
│   └── <sehir>/                #   her şehrin index.html'i + ayrı küçük GeoJSON veri dosyaları
├── output/                    # pipeline.py tarafından üretilir, git'e dahil değil
│   └── <sehir>_hvi_map.html  #   tamamen çevrimdışı, tek dosyalık harita (çift tıklayıp açılabilir)
├── data/                      # pipeline.py tarafından üretilir, git'e dahil değil
│   ├── raw/<sehir>/           #   indirilen Landsat bantları, OSM özütü, nüfus CSV'leri (şehir bazlı ayrılır)
│   └── processed/<sehir>/     #   LST/NDVI mozaikleri, ara GeoJSON'lar (şehir bazlı ayrılır)
├── CONTRIBUTING.md            # Yeni şehir ekleme adımları
├── requirements.txt
├── requirements-dev.txt       # Test bağımlılıkları (pytest)
├── Dockerfile / .dockerignore # Tek komutla tekrar üretilebilir çalışma ortamı
├── LICENSE                    # MIT
└── README.md
```

## Bilinen sınırlamalar

- **Bulut kapanması**: bazı yıllarda İzmir üzerinde %30 altı bulutlu bir
  yaz sahnesi bulunamayabilir; bu durumda `MAX_CLOUD_COVER` gevşetilebilir
  ama sonuç kalitesi düşer.
- **Yaş verisinin çözünürlüğü**: yaşlı nüfus oranı ilçe seviyesinde -
  mahalle-içi gerçek dağılım bundan daha değişken olabilir.
- **Tek gündüz anlık görüntüsü**: yol bazlı LST, sahnenin çekildiği saatteki
  (Landsat için genelde öğleden sonraya yakın) sıcaklığı yansıtır. Gece ısı
  adası etkisi (genelde daha güçlü olduğu bilinir) `--night-lst` bayrağıyla
  ayrı bir katman olarak eklenebilir (MODIS, 1 km çözünürlük) ama bu katman
  yol değil mahalle ölçeğindedir ve HVI skoruna dahil değildir - bkz.
  `core/night_lst.py` ve aşağıdaki Metodoloji bölümü.
- **10 metrelik yol tamponu**: sıcaklık ve NDVI örneklemesinde kullanılan
  bu dar tampon, çok dar sokaklarda komşu bir yolun etkisini
  karıştırabilir; çok geniş bulvarlarda ise koridorun tamamını
  kapsamayabilir.
- **150 metrelik yapılaşma tamponu**: bina yoğunluğu için seçilen bu
  yarıçap makul bir kentsel doku ölçeğidir ama tek bir seçimdir; komşu
  yolların tamponları örtüştüğü için yakın yollar benzer yoğunluk değeri
  alır, yani bu bileşen yol ölçeğinden çok mahalle ölçeğinde ayrıştırır.
- **SEGE tablosu elle aktarılmıştır**: `sege_2022_ilce.csv` içindeki
  skorlar resmi rapordan elle çıkarılmıştır; 30 ilçenin tamamı T.C. Sanayi
  ve Teknoloji Bakanlığı'nın resmi SEGE-2022 raporuyla satır satır
  karşılaştırılmış ve doğrulanmıştır. Yine de rapor güncellendiğinde bu
  dosyanın elle yeniden kontrol edilmesi gerekir.
- **Sosyoekonomik bileşen ilçe seviyesinde**: SEGE-2022 skoru da (yaşlı/
  çocuk oranı gibi) ilçe seviyesinde - mahalle-içi gerçek dağılım bundan
  daha değişken olabilir. Ayrıca 2022 tarihli, tek seferlik bir araştırma;
  gelecekte güncellenmiş bir SEGE raporu yayımlanırsa
  `sege_2022_ilce.csv` güncellenmelidir.
- **Eskişehir'de bir kademe daha kaba çözünürlük**: İzmir'in mahalle
  seviyesinde CKAN nüfus verisinin aksine, Eskişehir'in adapter'ı yaşlı/
  çocuk oranı için ilçe bazlı bir TÜİK yayını bulamadığından İL'in genel
  yaş dağılımını her iki ilçeye de aynı şekilde uyguluyor; nüfus yoğunluğu
  da mahalle değil ilçe bazında sabit. Gerçek ilçe-içi/mahalle-içi
  eşitsizlik bu yüzden İzmir'e göre daha az görünür (bkz.
  `cities/eskisehir/adapter.py` docstring'i).

## Lisans

MIT. Bkz. [LICENSE](LICENSE).
