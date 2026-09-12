"""Yeni bir şehir config.yaml'ının temel doğruluğunu kontrol eder.

Kullanım:
    python validate_city.py <sehir>

Kontrol ettikleri:
  1. `src/cities/<sehir>/config.yaml` var mı ve gerekli tüm alanları içeriyor mu
  2. bbox [batı, güney, doğu, kuzey] biçiminde ve koordinatlar geçerli mi
  3. Adapter modülü import edilebiliyor mu ve gerekli iki fonksiyonu
     (`fetch_population_data`, `build_neighborhood_layer`) uyguluyor mu
  4. OSM `.pbf` adresi erişilebilir mi
  5. Nüfus veri kaynağı (CKAN vb.) gerçekten erişilebilir mi (varsa)

Bu script hiçbir veri indirmez/işlemez - sadece config'in "çalışmaya hazır"
olup olmadığını hızlıca doğrular. Tam bir doğrulama için pipeline.py'ı
gerçekten çalıştırmak gerekir.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import requests  # noqa: E402

from core.city_config import CITIES_DIR, load_city_config, validate_config_dict  # noqa: E402

CKAN_CHECK_TIMEOUT_SECONDS = 15


def validate(city_id: str) -> list[str]:
    errors: list[str] = []
    config_path = CITIES_DIR / city_id / "config.yaml"

    if not config_path.exists():
        return [f"config.yaml bulunamadı: {config_path}"]

    import yaml
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    errors.extend(validate_config_dict(cfg))
    if errors:
        return errors  # temel şema geçersizse ilerisi anlamsız

    config = load_city_config(city_id)

    # Adapter import edilebiliyor mu ve gerekli iki fonksiyonu uyguluyor mu?
    try:
        from core.city_config import load_population_adapter
        adapter = load_population_adapter(config)
        for fn_name in ("fetch_population_data", "build_neighborhood_layer"):
            if not hasattr(adapter, fn_name):
                errors.append(f"Adapter '{config.population_adapter_path}' içinde '{fn_name}' fonksiyonu yok")
    except ImportError as e:
        errors.append(f"Adapter modülü import edilemedi ('{config.population_adapter_path}'): {e}")

    # OSM pbf URL'i erişilebilir mi? (indirmeden, sadece HEAD isteğiyle)
    try:
        r = requests.head(config.osm_pbf_url, timeout=CKAN_CHECK_TIMEOUT_SECONDS, allow_redirects=True)
        if r.status_code >= 400:
            errors.append(f"OSM pbf URL'i erişilemez görünüyor (HTTP {r.status_code}): {config.osm_pbf_url}")
    except requests.RequestException as e:
        errors.append(f"OSM pbf URL'ine bağlanılamadı: {config.osm_pbf_url} ({e})")

    # CKAN tabanlı nüfus kaynağı tanımlıysa erişilebilirliğini kontrol et.
    ckan_base = cfg.get("population", {}).get("ckan_base")
    if ckan_base:
        try:
            r = requests.get(f"{ckan_base}/api/3/action/site_read", timeout=CKAN_CHECK_TIMEOUT_SECONDS)
            if r.status_code >= 400:
                errors.append(f"CKAN portalına erişilemedi (HTTP {r.status_code}): {ckan_base}")
        except requests.RequestException as e:
            errors.append(f"CKAN portalına bağlanılamadı: {ckan_base} ({e})")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("city", help="src/cities/<sehir>/config.yaml içindeki şehir kimliği")
    args = parser.parse_args()

    errors = validate(args.city)
    if errors:
        print(f"'{args.city}' doğrulaması BAŞARISIZ:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"'{args.city}' doğrulaması geçti - config.yaml ve adapter kullanıma hazır görünüyor.")


if __name__ == "__main__":
    main()
