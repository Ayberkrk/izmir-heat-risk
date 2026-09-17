"""Landsat 8/9 sahnelerini indirir (Microsoft Planetary Computer).

Şehirden bağımsızdır: `CityConfig.bbox` ve `max_cloud_cover` dışında
hiçbir şey hardcode edilmez.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import planetary_computer
import pystac_client
import rasterio
import requests

from core.cache import is_cache_valid, write_cache_meta
from core.city_config import CityConfig
from core.paths import year_paths

# scene_metadata.json'un formül sürümü (bkz. core/cache.py). Daha önce bu
# fonksiyon düz `.exists()` kontrolü kullanıyordu; versiyonlu önbelleğe
# geçişin kendisi, sürüm dosyası taşımayan eski (karo başına tek sahne
# varsayan) metadata'yı otomatik geçersiz sayar.
SCENE_FETCH_VERSION = 1

CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
BANDS_TO_DOWNLOAD = {
    "red": "band4_red.tif",
    "nir08": "band5_nir.tif",
    "lwir11": "band10_thermal.tif",
    # Piksel düzeyinde bulut/gölge/kar maskesi için (bkz. core/raster.py,
    # qa_invalid_mask) - sahne düzeyindeki eo:cloud_cover filtresi tek
    # başına yeterli değil, düşük bulut oranlı bir sahnenin bulutunun küçük
    # bir kısmı doğrudan çalışma alanının üzerine düşebilir.
    "qa_pixel": "band_qa_pixel.tif",
}
DOWNLOAD_TIMEOUT_SECONDS = 300


def is_valid_geotiff(path: Path) -> bool:
    """Dosyanın var olmasının ötesinde gerçekten açılabilir olduğunu doğrular.

    Yarıda kesilen indirmeler "var ama bozuk" dosya bırakır; sadece
    `.exists()` kontrolü bunu yakalamaz.
    """
    if not path.exists():
        return False
    try:
        with rasterio.open(path) as src:
            src.read(1, window=((0, 1), (0, 1)))
        return True
    except Exception:
        return False


def select_best_scenes_per_tile(items, max_per_tile: int = 1) -> dict[tuple[int, int], list]:
    """Sahneleri karoya (path/row) göre gruplayıp her karo için en az bulutlu
    `max_per_tile` kadarını döner (bulut oranına göre artan sırada).

    Saf/network gerektirmeyen bir fonksiyon - `items`'ın gerçek bir
    `pystac.Item` olması gerekmez, sadece `.id` ve
    `.properties["landsat:wrs_path"]`/`["landsat:wrs_row"]`/
    `["eo:cloud_cover"]` erişimini destekleyen herhangi bir obje olabilir
    (testlerde basit bir sahte obje kullanılır).

    `max_per_tile=1` (varsayılan), önceki tek-sahne-per-karo davranışıyla
    birebir aynıdır - çoklu sahne kompoziti için `max_per_tile` artırılır.
    """
    items_by_tile: dict[tuple[int, int], list] = defaultdict(list)
    for item in items:
        tile_id = (item.properties["landsat:wrs_path"], item.properties["landsat:wrs_row"])
        items_by_tile[tile_id].append(item)

    return {
        tile_id: sorted(tile_items, key=lambda it: it.properties.get("eo:cloud_cover", 999))[:max_per_tile]
        for tile_id, tile_items in items_by_tile.items()
    }


def download_band(item, asset_name: str, save_path: Path) -> None:
    url = item.assets[asset_name].href
    response = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def fetch_landsat_scenes(config: CityConfig, year: str, main_year: str, force: bool = False) -> Path:
    """Verilen yılın yaz aylarına ait en temiz Landsat sahnelerini indirir.

    Çalışma alanı birden fazla uydu karosuna (path/row) düştüğü için her
    karo için ayrı ayrı en az bulutlu `config.max_scenes_per_tile` sahne
    seçilir (bkz. select_best_scenes_per_tile); sonuç mozaiklenecek karo
    sayısı × sahne sayısı kadar parçadır.
    """
    data_raw, _ = year_paths(config.city_id, year, main_year)
    data_raw.mkdir(parents=True, exist_ok=True)
    metadata_path = data_raw / "scene_metadata.json"

    if is_cache_valid(metadata_path, SCENE_FETCH_VERSION, force=force):
        print(f"[{year}] scene_metadata.json zaten var, indirme atlanıyor")
        return metadata_path

    catalog = pystac_client.Client.open(CATALOG_URL, modifier=planetary_computer.sign_inplace)
    search = catalog.search(
        collections=["landsat-c2-l2"],
        bbox=config.bbox,
        datetime=f"{year}-07-01/{year}-08-31",
        query={
            "eo:cloud_cover": {"lt": config.max_cloud_cover},
            # Landsat 7'nin SLC-off veri boşlukları ve farklı bant
            # isimlendirmesi yüzünden sadece L8/L9 sahneleri kullanılır.
            "platform": {"in": ["landsat-8", "landsat-9"]},
        },
    )
    items = list(search.items())
    print(f"[{year}] {len(items)} aday sahne bulundu")

    best_items = select_best_scenes_per_tile(items, max_per_tile=config.max_scenes_per_tile)

    if not best_items:
        raise RuntimeError(
            f"[{year}] {config.name} için bbox={config.bbox} ve bulut oranı "
            f"<{config.max_cloud_cover} kriterlerine uyan Landsat sahnesi bulunamadı. "
            "MAX_CLOUD_COVER'ı gevşetmeyi veya tarih aralığını genişletmeyi deneyin."
        )

    scenes_meta = []
    for tile_id, tile_items in sorted(best_items.items()):
        for item in tile_items:
            scene_dir = data_raw / item.id
            scene_dir.mkdir(parents=True, exist_ok=True)

            for asset_name, filename in BANDS_TO_DOWNLOAD.items():
                save_path = scene_dir / filename
                if is_valid_geotiff(save_path):
                    continue
                if save_path.exists():
                    save_path.unlink()
                print(f"[{year}] indiriliyor: {item.id}/{filename}")
                download_band(item, asset_name, save_path)

            scenes_meta.append({
                "tile": f"{tile_id[0]}_{tile_id[1]}",
                "scene_id": item.id,
                "date": item.properties["datetime"][:10],
                "cloud_cover": item.properties["eo:cloud_cover"],
                "folder": item.id,
            })

    metadata = {"bbox": config.bbox, "bands": list(BANDS_TO_DOWNLOAD.values()),
                "catalog": CATALOG_URL, "scenes": scenes_meta}
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    write_cache_meta(metadata_path, SCENE_FETCH_VERSION)

    print(f"[{year}] {len(scenes_meta)} sahne indirildi")
    return metadata_path
