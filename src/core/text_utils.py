"""Şehir adapter'ları arasında paylaşılan küçük metin yardımcıları.

Türkçe yer adlarını OSM ile resmi istatistik CSV'leri arasında
karşılaştırılabilir hale getirmek için kullanılır - her iki kaynak da
büyük/küçük harf, "Mahallesi" eki gibi konularda tutarsız olabiliyor.
"""

from __future__ import annotations

import re

_TR_ASCII_MAP = str.maketrans({"İ": "I", "Ş": "S", "Ğ": "G", "Ü": "U", "Ö": "O", "Ç": "C"})


def normalize_name(s: str) -> str:
    """Türkçe yer adlarını karşılaştırılabilir standart forma çevirir."""
    s = str(s).upper().strip().translate(_TR_ASCII_MAP)
    s = re.sub(r"\s+MAHALLESI$", "", s)
    return re.sub(r"\s+", " ", s)
