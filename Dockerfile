# Bağımlılık kurulumu makineden makineye (özellikle rasterio/GDAL) sorun
# çıkarabildiği için - bu imaj "pip install çalışıyor mu" sorusunu bir kere
# çözüp herkese aynı ortamı verir. README'deki gibi Python 3.12 ile test
# edilmiştir.
FROM python:3.12-slim

WORKDIR /app

# rasterio/geopandas'ın PyPI tekerlekleri (wheel) GDAL/GEOS/PROJ'u zaten
# içeriyor - onlar için ayrı bir apt kurulumu gerekmez. Ama `python:3.12-
# slim` GDAL'ın kendisinin dinamik olarak bağlandığı bazı temel sistem
# kütüphanelerini (libexpat, libgomp) içermiyor - CI'daki `docker` job'ı
# (.github/workflows/tests.yml) bunu "ImportError: libexpat.so.1: cannot
# open shared object file" ile yakaladı (bkz. Actions run 35231356788).
# build-essential yalnızca bir bağımlılığın kaynak koddan derlenmesi
# gerektiği nadir durum için.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libexpat1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt constraints.txt .
# constraints.txt tam sürümleri sabitler - imajın "bugün çalışıyorsa
# yarın da aynı çalışır" garantisi buna dayanıyor (bkz. constraints.txt).
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY . .

# data/, output/, docs/*/data ve venv/ .dockerignore ile hariç tutulur -
# imaj sadece kodu taşır, ürettiği/indirdiği veriyi değil.
ENTRYPOINT ["python", "pipeline.py"]
CMD ["--city", "izmir", "--years", "2020", "2026", "--main-year", "2026"]
