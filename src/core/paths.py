"""Şehir bazlı dosya yolları.

Veri, `data/raw/<sehir>/` ve `data/processed/<sehir>/` altında şehir
kimliğine göre ayrılır - iki şehir aynı checkout'ta çalıştırıldığında OSM
pbf'leri, nüfus CSV'leri ve raster mozaikleri birbirine karışmaz. Çıktı
haritaları zaten dosya adında şehir kimliği taşıdığı için (`<sehir>_hvi_
map.html`) `output/` klasörü ayrılmadan paylaşılabilir.

Not: İzmir için bu klasörler önceden (şehir ayrımı eklenmeden önce) düz
`data/raw/` ve `data/processed/` altındaydı; mevcut önbellek yeniden
indirilmeden `data/raw/izmir/` ve `data/processed/izmir/` altına taşındı.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# GitHub Pages'in servis ettiği klasör (Settings → Pages → Branch: main,
# klasör: /docs). `output/`'un aksine git'e dahildir - her şehrin küçük,
# fetch tabanlı harita sürümü ve karşılaştırma sayfası burada yaşar.
DOCS_DIR = PROJECT_ROOT / "docs"

_DATA_RAW_ROOT = PROJECT_ROOT / "data" / "raw"
_DATA_PROC_ROOT = PROJECT_ROOT / "data" / "processed"


def city_data_raw(city_id: str) -> Path:
    return _DATA_RAW_ROOT / city_id


def city_data_proc(city_id: str) -> Path:
    return _DATA_PROC_ROOT / city_id


# İzmir'in şehir ayrımı eklenmeden önceki OSM pbf dosya adı. Bu tek yerde
# tutulur - roads.py, hvi.py ve pipeline.py'nin üçü de aynı geriye dönük
# uyumluluk kontrolünü kopyalamak yerine `resolve_pbf_path`'i çağırır.
_LEGACY_IZMIR_PBF_FILENAME = "aegean-latest.osm.pbf"


def resolve_pbf_path(city_id: str) -> Path:
    """Bir şehrin OSM pbf dosya yolunu döndürür.

    Standart ad `<city_id>.osm.pbf` diskte yoksa, İzmir için şehir ayrımı
    eklenmeden önce kullanılan `aegean-latest.osm.pbf` adına bakar - böylece
    mevcut İzmir kullanıcıları dosyayı yeniden indirmek zorunda kalmaz. Yeni
    bir şehir için bu her zaman standart adı döndürür (legacy dosya hiç
    var olmadığından core/hiçbir şey şehre özel kalmaz).
    """
    data_raw = city_data_raw(city_id)
    pbf_path = data_raw / f"{city_id}.osm.pbf"
    legacy_pbf_path = data_raw / _LEGACY_IZMIR_PBF_FILENAME
    if not pbf_path.exists() and legacy_pbf_path.exists():
        return legacy_pbf_path
    return pbf_path


def year_paths(city_id: str, year: str, main_year: str) -> tuple[Path, Path]:
    """Bir şehrin/yılın ham/işlenmiş veri klasörlerini döndürür.

    Ana yıl (main_year) şehrin düz `data/raw/<sehir>/` ve
    `data/processed/<sehir>/` klasörlerini kullanır; diğer yıllar
    `data/raw/<sehir>/<year>/` gibi alt klasörlere gider. Böylece tek
    yıllık kullanımda dosya yolları sade kalır.
    """
    data_raw, data_proc = city_data_raw(city_id), city_data_proc(city_id)
    if year == main_year:
        return data_raw, data_proc
    return data_raw / year, data_proc / year
