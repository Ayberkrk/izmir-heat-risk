# Bağımlılık kurulumu makineden makineye (özellikle rasterio/GDAL) sorun
# çıkarabildiği için - bu imaj "pip install çalışıyor mu" sorusunu bir kere
# çözüp herkese aynı ortamı verir. README'deki gibi Python 3.12 ile test
# edilmiştir.
FROM python:3.12-slim

WORKDIR /app

# rasterio/geopandas'ın PyPI tekerlekleri (wheel) GDAL/GEOS/PROJ'u zaten
# içeriyor - ayrı bir apt kurulumu gerekmez. build-essential yalnızca bir
# bağımlılığın kaynak koddan derlenmesi gerektiği nadir durum için.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# data/, output/, docs/*/data ve venv/ .dockerignore ile hariç tutulur -
# imaj sadece kodu taşır, ürettiği/indirdiği veriyi değil.
ENTRYPOINT ["python", "pipeline.py"]
CMD ["--city", "izmir", "--years", "2020", "2026", "--main-year", "2026"]
