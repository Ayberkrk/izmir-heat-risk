"""Ara çıktı dosyaları için basit sürüm damgalı önbellek geçerliliği.

`roads_timeseries.geojson` ve `roads_with_hvi.geojson` üretimi pahalıdır
(uydu mozaikleri, OSM sorguları, mekansal join'ler); bu yüzden dosya zaten
varsa yeniden hesaplanmaz. Ama formül değiştiğinde (ör. `hvi.py`'deki
bileşen sayısı veya birleştirme yöntemi) eski dosya sessizce güncel gibi
kullanılırdı - bunu önlemek için her üretici modül kendi sürüm numarasını
küçük bir `.meta.json` yan dosyasına yazar; sürüm uyuşmazsa önbellek
geçersiz sayılır.
"""

from __future__ import annotations

import json
from pathlib import Path


def _meta_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".meta.json")


def is_cache_valid(output_path: Path, version: int, force: bool = False) -> bool:
    """Çıktı dosyası, verilen sürüm için hâlâ geçerli mi?

    `force=True` ise (CLI'dan --force ile) her zaman False döner - dosya
    zaten güncel olsa bile yeniden hesaplama zorlanır.
    """
    if force:
        return False
    if not output_path.exists():
        return False
    meta_path = _meta_path(output_path)
    if not meta_path.exists():
        # Bu mekanizmadan önce üretilmiş eski bir dosya olabilir - güvenli
        # taraf, geçersiz saymak ve yeniden hesaplamaktır.
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return meta.get("version") == version


def write_cache_meta(output_path: Path, version: int) -> None:
    _meta_path(output_path).write_text(json.dumps({"version": version}))
