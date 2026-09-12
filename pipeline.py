"""Çok şehirli kentsel ısı adası ve Isı Hassasiyet Endeksi (HVI) analiz hattı.

Uçtan uca akış:
  1. Landsat 8/9 sahnelerini indir (Microsoft Planetary Computer)
  2. Yüzey sıcaklığı (LST) ve NDVI hesaplayıp sahneleri mozaikle
  3. OSM yol ağını çek, her yıl için LST/NDVI'yi yollara ata
  4. Nüfus yoğunluğu, yaşlı/çocuk nüfus oranı, ağaç örtüsü, sağlık/yeşil
     alan erişimi ve yapılaşma yoğunluğunu birleştiren çok bileşenli Isı
     Hassasiyet Endeksini (HVI) hesapla
  5. Yıl seçmeli, kategorilere göre tembel yüklenen interaktif harita üret

Kullanım:
    python pipeline.py --city izmir --years 2020 2026 --main-year 2026 --open

Şehir parametreleri `src/cities/<sehir>/config.yaml` içinde tanımlanır -
yeni bir şehir eklemek için CONTRIBUTING.md'ye bakın.

Ara çıktılar `data/raw/` ve `data/processed/` altına yazılır ve zaten
mevcutlarsa yeniden hesaplanmaz - script yarıda kesilse bile kaldığı
yerden devam edebilir.
"""

from __future__ import annotations

import argparse
import sys
import warnings
import webbrowser
from pathlib import Path

# pandas/geopandas'ın gürültülü uyarıları bilinçli olarak susturuluyor, ama
# hesaplama hatasına işaret edebilecek sayısal ve coğrafi uyarılar (ör.
# coğrafi CRS'te merkez noktası hesaplama) görünür bırakılıyor.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.city_config import load_city_config  # noqa: E402
from core.hvi import compute_heat_vulnerability_index  # noqa: E402
from core.map_builder import build_hvi_map  # noqa: E402
from core.raster import build_lst_ndvi_mosaic  # noqa: E402
from core.roads import compute_road_risk_timeseries  # noqa: E402
from core.satellite import fetch_landsat_scenes  # noqa: E402


def run(city_id: str, years: list[str], main_year: str, open_browser: bool) -> Path:
    config = load_city_config(city_id)
    print(f"Şehir: {config.name} ({city_id}) | bbox={config.bbox} | yıllar={years}")

    for year in years:
        fetch_landsat_scenes(config, year, main_year)
        build_lst_ndvi_mosaic(config, year, main_year)

    roads = compute_road_risk_timeseries(config, years, main_year)
    compute_heat_vulnerability_index(config, years, roads)
    output_html = build_hvi_map(config, years, main_year)

    if open_browser:
        # macOS'a özel `open` komutu yerine taşınabilir yol.
        webbrowser.open(output_html.resolve().as_uri())

    return output_html


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", default="izmir", help="src/cities/<sehir>/config.yaml içindeki şehir kimliği")
    parser.add_argument("--years", nargs="+", default=["2020", "2026"], help="Karşılaştırılacak yıllar")
    parser.add_argument("--main-year", default="2026", help="Düz klasör yapısını kullanacak referans yıl")
    parser.add_argument("--open", action="store_true", help="Harita üretildikten sonra tarayıcıda aç")
    args = parser.parse_args()

    run(args.city, args.years, args.main_year, args.open)


if __name__ == "__main__":
    main()
