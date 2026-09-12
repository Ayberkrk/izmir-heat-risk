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
