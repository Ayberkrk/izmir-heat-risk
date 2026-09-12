"""İnteraktif HVI haritası üretici.

Tooltip artık sadece nihai HVI yüzdesini değil, o skoru oluşturan her
bileşenin kısa, anlaşılır bir dökümünü de gösterir (ör. "Sıcaklık: yüksek,
Ağaç örtüsü: çok düşük, Hastaneye uzaklık: uzak...") - kullanıcı "bu yolun
riski neden yüksek?" sorusuna doğrudan haritadan cevap bulabilir.
"""

from __future__ import annotations

import json
from pathlib import Path

import folium
import geopandas as gpd

from core.city_config import CityConfig
from core.hvi import CATEGORY_COLORS_5, CATEGORY_ORDER_5
from core.paths import OUTPUT_DIR, city_data_proc

_COMPONENT_LABELS = [
    ("_label_saglik", "Hastaneye uzaklık"),
    ("_label_yesil", "Yeşil alana uzaklık"),
    ("_label_yapilasma", "Yapılaşma yoğunluğu"),
    ("_label_nufus", "Nüfus yoğunluğu"),
    ("_label_yasli", "Yaşlı nüfus oranı"),
    ("_label_cocuk", "Çocuk nüfus oranı"),
    ("_label_sosyoekonomik", "Sosyoekonomik gelişmişlik"),  # bazı şehirlerde yok - sütun yoksa atlanır
]


def swatch(hex_color: str) -> str:
    return (f'<span style="display:inline-block;width:10px;height:10px;'
            f'border-radius:2px;background:{hex_color};margin-right:6px;'
            f'vertical-align:middle;"></span>')


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
        return " · ".join(pieces)

    roads[f"_aciklama_str_{year}"] = roads.apply(row_text, axis=1)


def build_hvi_map(config: CityConfig, years: list[str], default_year: str) -> Path:
    """Kategori bazlı tembel yükleme + yıl seçici içeren interaktif harita üretir.

    44 bin yolun 5 kategorisini aynı anda çizmek tarayıcıyı kilitliyordu;
    bu yüzden sayfa açıldığında hiçbir katman çizili değil - kullanıcı bir
    kategoriyi işaretlediği an JavaScript sadece o kategorinin verisini
    yükler (`overlayadd` olayı). Yıl değiştirmek de aynı mekanizmayı
    kullanır: sadece o an açık olan katmanlar yeniden doldurulur.
    """
    output_html = OUTPUT_DIR / f"{config.city_id}_hvi_map.html"
    roads = gpd.read_file(city_data_proc(config.city_id) / "roads_with_hvi.geojson")

    cat_col_default = f"hvi_category_{default_year}"
    pct_col_default = f"hvi_percentage_{default_year}"
    category_labels = {}
    for cat in CATEGORY_ORDER_5:
        subset = roads[roads[cat_col_default] == cat][pct_col_default]
        category_labels[cat] = f"{cat} ({subset.min():.1f}-{subset.max():.1f})" if len(subset) else cat

    for year in years:
        roads[f"_hvi_str_{year}"] = roads[f"hvi_percentage_{year}"].apply(
            lambda v: f"%{v:.0f}" if v == v else "Veri yok"
        )
        _build_explanation_column(roads, year)
    roads["_mahalle_str"] = roads["mahalle_adi"].fillna("Bilinmiyor")

    bounds = roads.total_bounds
    m = folium.Map(
        location=[(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2],
        zoom_start=12, tiles="OpenStreetMap", control_scale=True,
    )

    geojson_vars, group_vars = {}, {}
    data_by_year = {y: {} for y in years}

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

        for year in years:
            year_subset = roads[roads[f"hvi_category_{year}"] == cat]
            year_cols = ["geometry", "name", "_mahalle_str", f"_hvi_str_{year}", f"_aciklama_str_{year}"]
            year_data = year_subset[year_cols].rename(
                columns={f"_hvi_str_{year}": "_hvi_str", f"_aciklama_str_{year}": "_aciklama_str"}
            )
            data_by_year[year][cat] = year_data.__geo_interface__

    folium.LayerControl(position="topright", collapsed=False).add_to(m)

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
    <div style='position: fixed; bottom: 30px; left: 30px; z-index: 1000;
        background: rgba(20,20,20,0.9); color: white; padding: 14px 18px;
        border-radius: 8px; font-family: Arial, sans-serif; font-size: 13px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.5); max-width: 280px;'>
        <b style='font-size:14px'>Isı Hassasiyet Endeksi (HVI)</b><br>
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
    """
    m.get_root().html.add_child(folium.Element(control_html))

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
    }});
    </script>
    """
    m.get_root().html.add_child(folium.Element(lazy_load_html))

    OUTPUT_DIR.mkdir(exist_ok=True)
    m.save(str(output_html))
    print(f"Kaydedildi: {output_html} ({output_html.stat().st_size / 1e6:.1f} MB)")
    return output_html
