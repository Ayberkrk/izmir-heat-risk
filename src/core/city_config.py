"""Şehirden bağımsız yapılandırma yükleyici.

Her şehir `cities/<sehir>/config.yaml` dosyasıyla tanımlanır. Bu modül
sadece o dosyayı okuyup basit doğrulama yapan, tip güvenli bir arayüz
sağlar - pipeline'ın geri kalanı hiçbir yerde şehir adını hardcode etmez.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CITIES_DIR = PROJECT_ROOT / "src" / "cities"

# `landsat` isteğe bağlıdır - tek alanı (`max_cloud_cover`) makul bir
# varsayılana sahip, bu yüzden zorunlu listede yer almaz.
REQUIRED_TOP_KEYS = ["city", "osm", "population"]
REQUIRED_CITY_KEYS = ["name", "bbox", "crs"]
REQUIRED_OSM_KEYS = ["pbf_url", "highway_types", "admin_level_ilce", "admin_level_mahalle"]
REQUIRED_POPULATION_KEYS = ["adapter"]


@dataclass
class CityConfig:
    """Bir şehrin tüm parametrelerini tutan tek nesne.

    `raw` alanı, adapter'ların ihtiyaç duyabileceği şehre özel ek anahtarlara
    (ör. CKAN dataset ID'leri) erişim için ham sözlüğü de saklar - böylece
    her yeni şehre özel alan için bu dataclass'ı genişletmek gerekmez.
    """

    city_id: str
    name: str
    bbox: list[float]  # [batı, güney, doğu, kuzey]
    crs: str
    max_cloud_cover: int
    osm_pbf_url: str
    drive_highway_types: list[str]
    admin_level_ilce: str
    admin_level_mahalle: str
    population_adapter_path: str
    buffer_meters: int = 10
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def config_dir(self) -> Path:
        return CITIES_DIR / self.city_id


def validate_config_dict(cfg: dict) -> list[str]:
    """config sözlüğünü doğrular, hata mesajlarının listesini döndürür (boşsa geçerli)."""
    errors: list[str] = []
    for key in REQUIRED_TOP_KEYS:
        if key not in cfg:
            errors.append(f"Üst seviyede eksik alan: '{key}'")
    if errors:
        return errors

    city = cfg["city"]
    for key in REQUIRED_CITY_KEYS:
        if key not in city:
            errors.append(f"'city' altında eksik alan: '{key}'")
    bbox = city.get("bbox")
    if bbox is not None:
        if not (isinstance(bbox, list) and len(bbox) == 4):
            errors.append("'city.bbox' [batı, güney, doğu, kuzey] biçiminde 4 elemanlı olmalı")
        else:
            west, south, east, north = bbox
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                errors.append(f"'city.bbox' geçersiz koordinat aralığı: {bbox}")

    osm = cfg.get("osm", {})
    for key in REQUIRED_OSM_KEYS:
        if key not in osm:
            errors.append(f"'osm' altında eksik alan: '{key}'")

    population = cfg.get("population", {})
    for key in REQUIRED_POPULATION_KEYS:
        if key not in population:
            errors.append(f"'population' altında eksik alan: '{key}'")

    return errors


def load_city_config(city_id: str) -> CityConfig:
    config_path = CITIES_DIR / city_id / "config.yaml"
    if not config_path.exists():
        available = [p.name for p in CITIES_DIR.iterdir() if (p / "config.yaml").exists()] if CITIES_DIR.exists() else []
        raise FileNotFoundError(
            f"'{city_id}' için config bulunamadı: {config_path}\n"
            f"Mevcut şehirler: {available or '(hiçbiri)'}"
        )

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    errors = validate_config_dict(cfg)
    if errors:
        raise ValueError(f"{config_path} geçersiz:\n- " + "\n- ".join(errors))

    city, landsat, osm, population = cfg["city"], cfg.get("landsat", {}), cfg["osm"], cfg["population"]

    return CityConfig(
        city_id=city_id,
        name=city["name"],
        bbox=city["bbox"],
        crs=city["crs"],
        max_cloud_cover=landsat.get("max_cloud_cover", 30),
        osm_pbf_url=osm["pbf_url"],
        drive_highway_types=osm["highway_types"],
        admin_level_ilce=str(osm["admin_level_ilce"]),
        admin_level_mahalle=str(osm["admin_level_mahalle"]),
        population_adapter_path=population["adapter"],
        buffer_meters=cfg.get("roads", {}).get("buffer_meters", 10),
        raw=cfg,
    )


def load_population_adapter(config: CityConfig):
    """Şehre özel demografi adapter modülünü dinamik olarak import eder.

    Adapter, `fetch_population_data(config)` ve
    `build_neighborhood_layer(pbf_path, population_paths, config)`
    fonksiyonlarını uygulamak zorundadır (bkz. CONTRIBUTING.md).
    """
    return importlib.import_module(config.population_adapter_path)
