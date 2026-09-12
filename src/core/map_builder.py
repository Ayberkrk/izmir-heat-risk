"""İnteraktif HVI haritası üretici.

Tooltip sadece nihai HVI yüzdesini değil, o skoru oluşturan her bileşenin
kısa, anlaşılır bir dökümünü de gösterir (ör. "Sıcaklık: yüksek, Ağaç
örtüsü: çok düşük, Hastaneye uzaklık: uzak...") - kullanıcı "bu yolun
riski neden yüksek?" sorusuna doğrudan haritadan cevap bulabilir.

İki farklı çıktı üretilir:
  - `output/<sehir>_hvi_map.html`: tüm yılların/kategorilerin verisi tek
    dosyaya gömülü, tamamen çevrimdışı (dosyayı çift tıklayıp açmak yeterli).
    Büyük (İzmir için ~60 MB) ve git'e dahil değil.
  - `docs/<sehir>/`: aynı harita, ama veri her kategori/yıl için ayrı küçük
    GeoJSON dosyalarına bölünmüş ve tarayıcı sadece kullanıcının açtığı
    katmanı `fetch()` ile indiriyor. GitHub Pages'te barındırmak için
    (Settings → Pages → Branch: main /docs) bu klasör kullanılır - ilk
    sayfa yükü birkaç yüz KB'a iner, geri kalan veri talep üzerine gelir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import folium
import geopandas as gpd

from core.city_config import CityConfig
from core.hvi import CATEGORY_COLORS_5, CATEGORY_ORDER_5, bucket_5
from core.paths import DOCS_DIR, OUTPUT_DIR, city_data_proc

_COMPONENT_LABELS = [
    ("_label_saglik", "Hastaneye uzaklık"),
    ("_label_yesil", "Yeşil alana uzaklık"),
    ("_label_yapilasma", "Yapılaşma yoğunluğu"),
    ("_label_nufus", "Nüfus yoğunluğu"),
    ("_label_yasli", "Yaşlı nüfus oranı"),
    ("_label_cocuk", "Çocuk nüfus oranı"),
    ("_label_sosyoekonomik", "Sosyoekonomik gelişmişlik"),  # bazı şehirlerde yok - sütun yoksa atlanır
]

# GeoJSON'a yazılan koordinatların ondalık hassasiyeti. 5 basamak ~1.1 m'ye
# denk gelir - yol ölçeğinde bir görselleştirme için gereğinden fazla bile;
# ham Landsat/OSM verisi genelde 10+ basamak taşır, bu da dosya boyutunun
# önemli bir kısmını gereksiz yere şişirir.
COORD_PRECISION = 5


def swatch(hex_color: str) -> str:
    return (f'<span style="display:inline-block;width:10px;height:10px;'
            f'border-radius:2px;background:{hex_color};margin-right:6px;'
            f'vertical-align:middle;"></span>')


def _round_coords(node: Any) -> Any:
    """GeoJSON koordinat dizilerindeki float'ları yuvarlar (dosya boyutu için)."""
    if isinstance(node, float):
        return round(node, COORD_PRECISION)
    if isinstance(node, list):
        return [_round_coords(child) for child in node]
    if isinstance(node, dict):
        return {key: (_round_coords(value) if key != "properties" else value) for key, value in node.items()}
    return node


def _slugify(text: str) -> str:
    """Kategori adını dosya adı olarak kullanılabilir hale getirir."""
    ascii_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    text = text.translate(ascii_map).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _build_explanation_column(roads: gpd.GeoDataFrame, year: str) -> None:
    """Bileşen etiketlerini tek bir okunabilir dizgede birleştirir (tooltip için)."""

    # Şehirde hiç üretilmemiş bir bileşen (ör. sosyoekonomik skoru olmayan
    # bir şehir) tooltip'te "Veri yok" satırı olarak görünmemeli, hiç
    # görünmemeli - mevcut sütunlar bir kez baştan belirlenir.
    present = [(col, label) for col, label in _COMPONENT_LABELS if col in roads.columns]

    def row_text(row) -> str:
        pieces = [f"Sıcaklık: {row.get(f'_label_sicaklik_{year}', 'Veri yok')}",
                  f"Ağaç örtüsü: {row.get(f'_label_agac_{year}', 'Veri yok')}"]
        for col, label in present:
            pieces.append(f"{label}: {row[col]}")
        # Tooltip hücresi innerHTML olarak basılıyor (bkz. folium'un ürettiği
        # `handleObject`), bu yüzden gerçek <br> satır sonu üretir - tek
        # satırlık " · " ile ayrılmış bir metin duvarı yerine her bileşen
        # kendi satırında, taranması daha kolay.
        return "<br>".join(pieces)

    roads[f"_aciklama_str_{year}"] = roads.apply(row_text, axis=1)


def _write_city_stats(config: CityConfig, roads: gpd.GeoDataFrame, years: list[str], default_year: str) -> None:
    """Şehirler arası karşılaştırma sayfası için küçük bir özet dosyası yazar.

    Bu dosya kasıtlı olarak küçüktür (birkaç yüz bayt) ve git'e dahil
    edilmesi amaçlanır - `build_docs_index.py` ham `roads_with_hvi.geojson`
    dosyasına (onlarca MB, gitignore'da) ihtiyaç duymadan, sadece bu özet
    üzerinden tüm şehirleri karşılaştırabilir.
    """
    pct_col = f"hvi_percentage_{default_year}"
    cat_col = f"hvi_category_{default_year}"
    valid = roads[pct_col].notna()
    top_mahalle = (
        roads.loc[valid].groupby("mahalle_adi")[pct_col].mean().sort_values(ascending=False)
    )
    stats = {
        "city_id": config.city_id,
        "name": config.name,
        "years": years,
        "default_year": default_year,
        "road_count": int(valid.sum()),
        "avg_hvi_percentage": round(float(roads.loc[valid, pct_col].mean()), 1),
        # value_counts() int'leri numpy.int64 döner - json.dumps bunu
        # serileştiremez, bu yüzden düz Python int'e çevriliyor.
        "category_counts": {k: int(v) for k, v in roads.loc[valid, cat_col].value_counts().items()},
        "top_risk_mahalle": top_mahalle.index[0] if len(top_mahalle) else None,
    }
    docs_dir = DOCS_DIR / config.city_id
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))


def _prepare_layers(roads: gpd.GeoDataFrame, years: list[str]):
    """Kategori/yıl bazlı alt kümeleri ve tooltip sütunlarını hazırlar (ortak adım)."""
    for year in years:
        roads[f"_hvi_str_{year}"] = roads[f"hvi_percentage_{year}"].apply(
            lambda v: f"%{v:.0f}" if v == v else "Veri yok"
        )
        _build_explanation_column(roads, year)
    roads["_mahalle_str"] = roads["mahalle_adi"].fillna("Bilinmiyor")

    data_by_year: dict[str, dict[str, dict]] = {y: {} for y in years}
    for cat in CATEGORY_ORDER_5:
        for year in years:
            year_subset = roads[roads[f"hvi_category_{year}"] == cat]
            year_cols = ["geometry", "name", "_mahalle_str", f"_hvi_str_{year}", f"_aciklama_str_{year}"]
            year_data = year_subset[year_cols].rename(
                columns={f"_hvi_str_{year}": "_hvi_str", f"_aciklama_str_{year}": "_aciklama_str"}
            )
            data_by_year[year][cat] = _round_coords(year_data.__geo_interface__)
    return data_by_year


# Folium'un style_function'ı, harita ilk kurulurken elindeki özellikler
# için JS tarafında SABİT bir renge çevrilir (bkz. üretilen HTML'deki
# `_styler` fonksiyonu - bir switch/default bloğu). Bu yüzden rengin
# özelliğe (ör. sıcaklık değerine) göre değişmesi gereken bir katman,
# yol kategorileriyle AYNI mantıkla (her biri sabit renkli ayrı bir
# FeatureGroup) kurulmalı - tek bir GeoJson'a "değere göre renklen"
# fonksiyonu vermek, sonradan `addData()` ile eklenen (tembel yüklenen)
# özellikler için çalışmaz.
NIGHT_LST_LABELS = ["Serin", "Ilıman", "Orta", "Sıcak", "Çok sıcak"]
NIGHT_LST_COLORS = dict(zip(NIGHT_LST_LABELS, ["#313695", "#74add1", "#fed976", "#fd8d3c", "#a50026"]))


def _load_night_lst(config: CityConfig, default_year: str) -> gpd.GeoDataFrame | None:
    """Varsa (`--night-lst` ile üretilmişse) mahalle bazlı gece LST verisini,
    yol kategorileriyle aynı 5'li yüzdelik dilim etiketiyle döner.
    """
    night_path = city_data_proc(config.city_id) / f"night_lst_by_mahalle_{default_year}.geojson"
    if not night_path.exists():
        return None
    night_gdf = gpd.read_file(night_path)
    night_gdf["_gece_bin"] = bucket_5(night_gdf["gece_lst_c"], NIGHT_LST_LABELS).astype(str)
    night_gdf["_gece_lst_str"] = night_gdf["gece_lst_c"].apply(lambda v: f"{v:.1f}°C" if v == v else "Veri yok")
    return night_gdf


def _base_map(config: CityConfig, roads: gpd.GeoDataFrame, years: list[str], default_year: str,
              night_gdf: gpd.GeoDataFrame | None):
    """Ortak folium haritasını (katmanlar, lejant, kontrol paneli) kurar."""
    cat_col_default = f"hvi_category_{default_year}"
    pct_col_default = f"hvi_percentage_{default_year}"
    category_labels = {}
    for cat in CATEGORY_ORDER_5:
        subset = roads[roads[cat_col_default] == cat][pct_col_default]
        category_labels[cat] = f"{cat} ({subset.min():.1f}-{subset.max():.1f})" if len(subset) else cat

    bounds = roads.total_bounds
    m = folium.Map(
        location=[(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2],
        zoom_start=12, tiles="OpenStreetMap", control_scale=True,
    )

    geojson_vars, group_vars = {}, {}
    for cat in CATEGORY_ORDER_5:
        color = CATEGORY_COLORS_5[cat]
        group = folium.FeatureGroup(name=swatch(color) + category_labels[cat], show=False)

        default_subset = roads[roads[cat_col_default] == cat]
        if len(default_subset) == 0:
            continue

        # Katman haritaya show=False ile eklendiği için görünmez; sadece
        # GeoJsonTooltip'in boş veriyle patlamasını önlemek için 1 örnek
        # geometri ile başlatılıyor.
        placeholder_cols = ["geometry", "name", "_mahalle_str", f"_hvi_str_{default_year}", f"_aciklama_str_{default_year}"]
        placeholder = default_subset.iloc[:1][placeholder_cols].rename(
            columns={f"_hvi_str_{default_year}": "_hvi_str", f"_aciklama_str_{default_year}": "_aciklama_str"}
        )

        geo = folium.GeoJson(
            placeholder.__geo_interface__,
            style_function=lambda feat, c=color: {"color": c, "weight": 2.5, "opacity": 0.85},
            tooltip=folium.GeoJsonTooltip(
                fields=["name", "_mahalle_str", "_hvi_str", "_aciklama_str"],
                aliases=["Yol", "Mahalle", "Risk Oranı", "Bileşenler"], sticky=True,
                style="max-width: 320px; white-space: normal;",
            ),
        )
        geo.add_to(group)
        group.add_to(m)
        geojson_vars[cat] = geo.get_name()
        group_vars[cat] = group.get_name()

    night_geojson_vars, night_group_vars = {}, {}
    if night_gdf is not None:
        for label in NIGHT_LST_LABELS:
            subset = night_gdf[night_gdf["_gece_bin"] == label]
            if len(subset) == 0:
                continue
            color = NIGHT_LST_COLORS[label]
            temp_range = f"{subset['gece_lst_c'].min():.1f}-{subset['gece_lst_c'].max():.1f}°C"
            group = folium.FeatureGroup(name=swatch(color) + f"Gece: {label} ({temp_range})", show=False)
            placeholder = subset.iloc[:1][["geometry", "mahalle_adi", "_gece_lst_str"]]
            geo = folium.GeoJson(
                placeholder.__geo_interface__,
                style_function=lambda feat, c=color: {"fillColor": c, "color": "#555", "weight": 0.5, "fillOpacity": 0.6},
                tooltip=folium.GeoJsonTooltip(fields=["mahalle_adi", "_gece_lst_str"],
                                               aliases=["Mahalle", "Ortalama gece LST"]),
            )
            geo.add_to(group)
            group.add_to(m)
            night_geojson_vars[label] = geo.get_name()
            night_group_vars[label] = group.get_name()

    # collapsed=True: katman listesi varsayılan kapalı bir simge olarak
    # başlar - açık haliyle (10 satır: 5 HVI + 5 gece kategorisi) özellikle
    # dar/mobil ekranlarda haritanın büyük kısmını kapatıyordu.
    folium.LayerControl(position="topright", collapsed=True).add_to(m)

    # Tek bir zemin harita (OpenStreetMap) olduğu için Leaflet'in otomatik
    # eklediği "temel katman" radio düğmesi hiçbir seçim sunmuyor, sadece
    # yer kaplıyor - CSS ile gizleniyor.
    m.get_root().html.add_child(folium.Element(
        "<style>.leaflet-control-layers-base, .leaflet-control-layers-separator "
        "{ display: none !important; }</style>"
    ))
    # HVI kategorileri ile gece ısı katmanları aynı düz listede aralarında
    # hiçbir ayrım olmadan görünüyordu; ilk "Gece:" satırının üstüne ince
    # bir başlık ekleniyor (bkz. aşağıdaki `load` script'i).
    m.get_root().html.add_child(folium.Element(f"""
    <script>
    window.addEventListener('load', function() {{
        var etiketler = document.querySelectorAll('.leaflet-control-layers-overlays label');
        for (var i = 0; i < etiketler.length; i++) {{
            if (etiketler[i].textContent.indexOf('Gece:') !== -1) {{
                var ayrac = document.createElement('div');
                ayrac.textContent = 'Gece Isı Haritası (mahalle, MODIS)';
                ayrac.style.cssText = 'margin-top:6px;padding-top:6px;border-top:1px solid #ccc;'
                    + 'font-size:11px;color:#666;text-transform:uppercase;letter-spacing:0.03em;';
                etiketler[i].parentNode.insertBefore(ayrac, etiketler[i]);
                break;
            }}
        }}
    }});
    </script>
    """))

    # Veri kaynağı künyesi şehre göre değişir; core kodu hiçbir şehrin
    # kaynağını hardcode etmemeli, config.yaml'daki `city.attribution`
    # anahtarından okunur (yoksa satır tamamen atlanır).
    attribution = config.raw.get("city", {}).get("attribution")
    attribution_html = f"{attribution}<br>" if attribution else ""

    legend_rows = "".join(
        f"{swatch(CATEGORY_COLORS_5[cat])}{category_labels[cat]}<br>" for cat in CATEGORY_ORDER_5
    )
    year_options = "".join(f"<option value='{y}'>{y}</option>" for y in sorted(years, reverse=True))
    control_html = f"""
    <div id='hviPanel' style='position: fixed; bottom: 30px; left: 30px; z-index: 1000;
        background: rgba(20,20,20,0.9); color: white; padding: 14px 18px;
        border-radius: 8px; font-family: Arial, sans-serif; font-size: 13px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.5); max-width: 280px;'>
        <div style='display:flex; align-items:center; justify-content:space-between;'>
            <b style='font-size:14px'>Isı Hassasiyet Endeksi (HVI)</b>
            <span id='hviPanelKapat' onclick="
                var g = document.getElementById('hviPanelIcerik');
                var kapali = g.style.display === 'none';
                g.style.display = kapali ? '' : 'none';
                this.textContent = kapali ? '−' : '+';
            " style='cursor:pointer; padding:0 4px; font-size:15px; user-select:none; color:#ccc;'>&minus;</span>
        </div>
        <div id='hviPanelIcerik'>
        <small>Sıcaklık, ağaç örtüsü, sağlık/yeşil alan erişimi, yapılaşma,
        nüfus yoğunluğu, yaşlı ve çocuk nüfus oranının birleşimi</small>
        <hr style='border-color:#555; margin:8px 0'>
        <b>Yıl:</b>
        <select id='yilSecici' style='font-size:14px; padding:4px 8px; border-radius:4px; width:90px;'>
            {year_options}
        </select>
        <hr style='border-color:#555; margin:8px 0'>
        {legend_rows}
        <hr style='border-color:#555; margin:8px 0'>
        <small>Bir yola tıklayınca/üzerine gelince skoru oluşturan tüm
        bileşenler görünür.<br>
        {attribution_html}
        Alan: {config.name} (metro alanı)</small>
        </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(control_html))

    loading_html = """
    <div id='yukleniyorKutusu' style='display:none; position: fixed; top: 10px; left: 50%;
        transform: translateX(-50%); z-index: 1000; background: rgba(20,20,20,0.85); color: #ddd;
        padding: 4px 14px; border-radius: 4px; font-family: Arial, sans-serif; font-size: 12px;'>
        Katman yükleniyor...
    </div>
    """
    m.get_root().html.add_child(folium.Element(loading_html))

    return m, geojson_vars, group_vars, night_geojson_vars, night_group_vars


def _prepare_night_data(night_gdf: gpd.GeoDataFrame | None) -> dict[str, dict]:
    if night_gdf is None:
        return {}
    result = {}
    for label in NIGHT_LST_LABELS:
        subset = night_gdf[night_gdf["_gece_bin"] == label][["geometry", "mahalle_adi", "_gece_lst_str"]]
        if len(subset) == 0:
            continue
        result[label] = _round_coords(subset.__geo_interface__)
    return result


def _night_layer_js(night_geojson_vars: dict, night_group_vars: dict, night_data_expr: str) -> str:
    """Gece LST katmanları için ortak JS - yıl seçiciye bağlı değil, her
    katman sadece bir kez (ilk açıldığında) yüklenir.
    """
    if not night_geojson_vars:
        return ""
    return f"""
        var geceGeoJsonAdlari = {json.dumps(night_geojson_vars)};
        var geceGrupAdlari = {json.dumps(night_group_vars)};
        var geceVerisi = {night_data_expr};
        var geceYuklendi = {{}};

        var geceGrupNesneToEtiket = {{}};
        for (var etiket in geceGrupAdlari) {{
            geceGrupNesneToEtiket[L.stamp(window[geceGrupAdlari[etiket]])] = etiket;
        }}

        harita.on('overlayadd', function(e) {{
            var etiket = geceGrupNesneToEtiket[L.stamp(e.layer)];
            if (!etiket || geceYuklendi[etiket]) {{ return; }}
            geceYuklendi[etiket] = true;
            window[geceGeoJsonAdlari[etiket]].addData(geceVerisi[etiket]);
        }});
    """


def _write_embedded(config: CityConfig, m: folium.Map, geojson_vars: dict, group_vars: dict,
                     data_by_year: dict, default_year: str,
                     night_geojson_vars: dict, night_group_vars: dict, night_data: dict) -> Path:
    """Tüm veriyi HTML'e gömen, tamamen çevrimdışı çalışan sürüm (output/)."""
    output_html = OUTPUT_DIR / f"{config.city_id}_hvi_map.html"

    lazy_load_html = f"""
    <script>
    // Folium'un kendi harita/katman kurulum script'i </body>'den sonra
    // çalışıyor; window[...] değişkenlerine sayfa yüklenmeden erişmek
    // "tanımsız" hatası veriyor. window.onload tüm script'ler bittikten
    // sonra tetiklenir.
    window.addEventListener('load', function() {{
        var harita = {m.get_name()};
        var tumVeriYilBazli = {json.dumps(data_by_year, ensure_ascii=False)};
        var geoJsonAdlari = {json.dumps(geojson_vars)};
        var grupAdlari = {json.dumps(group_vars)};
        var mevcutYil = '{default_year}';

        var grupNesneToKategori = {{}};
        for (var kategori in grupAdlari) {{
            grupNesneToKategori[L.stamp(window[grupAdlari[kategori]])] = kategori;
        }}

        function katmaniYukle(kategori) {{
            var geoJsonKatmani = window[geoJsonAdlari[kategori]];
            geoJsonKatmani.clearLayers();
            geoJsonKatmani.addData(tumVeriYilBazli[mevcutYil][kategori]);
        }}

        harita.on('overlayadd', function(e) {{
            var kategori = grupNesneToKategori[L.stamp(e.layer)];
            if (!kategori) {{ return; }}
            katmaniYukle(kategori);
        }});

        var secici = document.getElementById('yilSecici');
        secici.value = mevcutYil;
        secici.addEventListener('change', function() {{
            mevcutYil = this.value;
            for (var kategori in grupAdlari) {{
                var grup = window[grupAdlari[kategori]];
                if (harita.hasLayer(grup)) {{ katmaniYukle(kategori); }}
            }}
        }});

        {_night_layer_js(night_geojson_vars, night_group_vars, json.dumps(night_data, ensure_ascii=False))}
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(lazy_load_html))

    OUTPUT_DIR.mkdir(exist_ok=True)
    m.save(str(output_html))
    print(f"Kaydedildi (çevrimdışı, tek dosya): {output_html} ({output_html.stat().st_size / 1e6:.1f} MB)")
    return output_html


def _write_fetch_based(config: CityConfig, m: folium.Map, geojson_vars: dict, group_vars: dict,
                        data_by_year: dict, years: list[str], default_year: str,
                        night_geojson_vars: dict, night_group_vars: dict, night_data: dict) -> Path:
    """Veriyi ayrı küçük dosyalara bölen, GitHub Pages'e uygun sürüm (docs/<sehir>/)."""
    docs_dir = DOCS_DIR / config.city_id
    data_dir = docs_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Her (yıl, kategori) çifti için ayrı bir dosya - tarayıcı sadece
    # kullanıcının açtığı katmanı indirir, tüm yılların/kategorilerin
    # verisini önceden indirmez.
    file_map: dict[str, dict[str, str]] = {y: {} for y in years}
    for year in years:
        for cat, geo in data_by_year[year].items():
            filename = f"{_slugify(cat)}_{year}.geojson"
            (data_dir / filename).write_text(json.dumps(geo, ensure_ascii=False))
            file_map[year][cat] = f"data/{filename}"

    # Gece LST katmanı yıl seçiciye bağlı değil - kendi küçük dosyaları var.
    night_file_map = {}
    for label, geo in night_data.items():
        filename = f"gece-{_slugify(label)}.geojson"
        (data_dir / filename).write_text(json.dumps(geo, ensure_ascii=False))
        night_file_map[label] = f"data/{filename}"

    output_html = docs_dir / "index.html"
    night_js = ""
    if night_geojson_vars:
        night_js = f"""
        var geceDosyaYollari = {json.dumps(night_file_map, ensure_ascii=False)};
        var geceGeoJsonAdlari = {json.dumps(night_geojson_vars)};
        var geceGrupAdlari = {json.dumps(night_group_vars)};
        var geceYuklendi = {{}};

        var geceGrupNesneToEtiket = {{}};
        for (var etiket in geceGrupAdlari) {{
            geceGrupNesneToEtiket[L.stamp(window[geceGrupAdlari[etiket]])] = etiket;
        }}

        harita.on('overlayadd', function(e) {{
            var etiket = geceGrupNesneToEtiket[L.stamp(e.layer)];
            if (!etiket || geceYuklendi[etiket]) {{ return; }}
            geceYuklendi[etiket] = true;
            yukleniyorGoster();
            fetch(geceDosyaYollari[etiket])
                .then(function(r) {{ return r.json(); }})
                .then(function(veri) {{ window[geceGeoJsonAdlari[etiket]].addData(veri); yukleniyorGizle(); }})
                .catch(function(hata) {{ console.error('Gece LST katmanı yüklenemedi:', etiket, hata); yukleniyorGizle(); }});
        }});
        """

    fetch_load_html = f"""
    <script>
    window.addEventListener('load', function() {{
        var harita = {m.get_name()};
        var dosyaYollari = {json.dumps(file_map, ensure_ascii=False)};
        var geoJsonAdlari = {json.dumps(geojson_vars)};
        var grupAdlari = {json.dumps(group_vars)};
        var mevcutYil = '{default_year}';
        var onbellek = {{}};  // "{{yil}}|{{kategori}}" -> zaten indirilmiş veri

        // Ağ gecikmesinde kullanıcıya geri bildirim - aktif istek sayacı,
        // birden fazla katman aynı anda açılırsa kutunun erken kapanmasını önler.
        var aktifIstekSayisi = 0;
        function yukleniyorGoster() {{
            aktifIstekSayisi++;
            document.getElementById('yukleniyorKutusu').style.display = 'block';
        }}
        function yukleniyorGizle() {{
            aktifIstekSayisi = Math.max(0, aktifIstekSayisi - 1);
            if (aktifIstekSayisi === 0) {{
                document.getElementById('yukleniyorKutusu').style.display = 'none';
            }}
        }}

        var grupNesneToKategori = {{}};
        for (var kategori in grupAdlari) {{
            grupNesneToKategori[L.stamp(window[grupAdlari[kategori]])] = kategori;
        }}

        function katmaniYukle(kategori) {{
            var anahtar = mevcutYil + '|' + kategori;
            var geoJsonKatmani = window[geoJsonAdlari[kategori]];
            if (onbellek[anahtar]) {{
                geoJsonKatmani.clearLayers();
                geoJsonKatmani.addData(onbellek[anahtar]);
                return;
            }}
            yukleniyorGoster();
            fetch(dosyaYollari[mevcutYil][kategori])
                .then(function(r) {{ return r.json(); }})
                .then(function(veri) {{
                    onbellek[anahtar] = veri;
                    geoJsonKatmani.clearLayers();
                    geoJsonKatmani.addData(veri);
                    yukleniyorGizle();
                }})
                .catch(function(hata) {{ console.error('Katman yüklenemedi:', kategori, hata); yukleniyorGizle(); }});
        }}

        harita.on('overlayadd', function(e) {{
            var kategori = grupNesneToKategori[L.stamp(e.layer)];
            if (!kategori) {{ return; }}
            katmaniYukle(kategori);
        }});

        var secici = document.getElementById('yilSecici');
        secici.value = mevcutYil;
        secici.addEventListener('change', function() {{
            mevcutYil = this.value;
            for (var kategori in grupAdlari) {{
                var grup = window[grupAdlari[kategori]];
                if (harita.hasLayer(grup)) {{ katmaniYukle(kategori); }}
            }}
        }});

        {night_js}
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(fetch_load_html))
    m.save(str(output_html))
    data_size = sum(f.stat().st_size for f in data_dir.glob("*.geojson"))
    print(f"Kaydedildi (barındırma için, fetch tabanlı): {output_html} "
          f"(sayfa {output_html.stat().st_size / 1e3:.0f} KB + veri {data_size / 1e6:.1f} MB, talep üzerine)")
    return output_html


def build_hvi_map(config: CityConfig, years: list[str], default_year: str) -> Path:
    """Kategori bazlı tembel yükleme + yıl seçici içeren interaktif harita üretir.

    44 bin yolun 5 kategorisini aynı anda çizmek tarayıcıyı kilitliyordu;
    bu yüzden sayfa açıldığında hiçbir katman çizili değil - kullanıcı bir
    kategoriyi işaretlediği an JavaScript sadece o kategorinin verisini
    yükler (`overlayadd` olayı). Yıl değiştirmek de aynı mekanizmayı
    kullanır: sadece o an açık olan katmanlar yeniden doldurulur.

    İki çıktı üretilir - bkz. modül docstring'i.
    """
    roads = gpd.read_file(city_data_proc(config.city_id) / "roads_with_hvi.geojson")
    night_gdf = _load_night_lst(config, default_year)

    data_by_year = _prepare_layers(roads, years)
    night_data = _prepare_night_data(night_gdf)

    m, geojson_vars, group_vars, night_geojson_vars, night_group_vars = _base_map(
        config, roads, years, default_year, night_gdf
    )
    _write_city_stats(config, roads, years, default_year)
    offline_html = _write_embedded(config, m, geojson_vars, group_vars, data_by_year, default_year,
                                    night_geojson_vars, night_group_vars, night_data)

    # folium.Map nesnesi bir kez kaydedildikten sonra JS elementleri birikir;
    # barındırma sürümü için haritayı sıfırdan kurmak, iki script'in
    # birbirine karışmasını önler.
    m2, geojson_vars2, group_vars2, night_geojson_vars2, night_group_vars2 = _base_map(
        config, roads, years, default_year, night_gdf
    )
    _write_fetch_based(config, m2, geojson_vars2, group_vars2, data_by_year, years, default_year,
                        night_geojson_vars2, night_group_vars2, night_data)

    return offline_html
