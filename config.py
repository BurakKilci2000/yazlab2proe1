"""
Projenin tüm ayarları bu dosyada toplanır.

Gizli bilgiler (API anahtarları, veritabanı adresi) koda yazılmaz;
proje klasöründeki .env dosyasından okunur. .env dosyası .gitignore
içinde olduğu için Git'e/teslim arşivine yanlışlıkla girmez.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Veritabanı (MongoDB zorunlu) -----------------------------------------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "kocaeli_haber")

# --- Google API anahtarları -----------------------------------------------
# Geocoding anahtarı yalnızca sunucuda kullanılır, tarayıcıya hiç gönderilmez.
GOOGLE_GEOCODING_API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY", "").strip()
# Maps JavaScript anahtarı tarayıcıda görünmek zorundadır; bu yüzden Google
# Cloud'da HTTP referrer kısıtlaması (ör. http://localhost:5000/*) konulmalıdır.
GOOGLE_MAPS_JS_API_KEY = os.getenv("GOOGLE_MAPS_JS_API_KEY", "").strip()
GOOGLE_MAPS_MAP_ID = os.getenv("GOOGLE_MAPS_MAP_ID", "").strip() or "DEMO_MAP_ID"


# --- Servis seçimi -------------------------------------------------------------
# "auto" (varsayılan): Google anahtarı tanımlıysa Google, değilse ücretsiz OpenStreetMap
# servisleri kullanılır. İstenirse .env içinde açıkça "google" / "nominatim" / "osm"
# yazılabilir. Proje dokümanı harita için Google Maps istediğinden teslimde
# MAP_PROVIDER=google olmalıdır; "osm" yalnızca geçici/test amaçlıdır.
def _provider(name: str, google_key: str, allowed: tuple[str, str]) -> str:
    value = os.getenv(name, "auto").strip().lower()
    if value in allowed:
        return value
    return allowed[0] if google_key else allowed[1]


GEOCODER = _provider("GEOCODER", GOOGLE_GEOCODING_API_KEY, ("google", "nominatim"))
MAP_PROVIDER = _provider("MAP_PROVIDER", GOOGLE_MAPS_JS_API_KEY, ("google", "osm"))

# Nominatim kullanım kuralları: uygulamayı tanıtan bir User-Agent zorunludur,
# saniyede en fazla 1 istek yapılabilir ve sonuçlar önbelleğe alınmalıdır.
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
NOMINATIM_EMAIL = os.getenv("NOMINATIM_EMAIL", "").strip()
NOMINATIM_MIN_INTERVAL = 1.1  # saniye

# --- Scraping ----------------------------------------------------------------
SCRAPE_DAYS = _int("SCRAPE_DAYS", 3)                      # son kaç günün haberi
SCRAPE_INTERVAL_MINUTES = _int("SCRAPE_INTERVAL_MINUTES", 60)
SCRAPE_ON_STARTUP = os.getenv("SCRAPE_ON_STARTUP", "1") == "1"
MAX_ARTICLES_PER_SITE = _int("MAX_ARTICLES_PER_SITE", 150)
STOP_AFTER_OLD_ARTICLES = _int("STOP_AFTER_OLD_ARTICLES", 12)
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 20)
REQUEST_DELAY_SECONDS = _float("REQUEST_DELAY_SECONDS", 0.7)  # siteleri yormamak için

# --- Benzerlik (duplicate) analizi --------------------------------------------
SIMILARITY_THRESHOLD = _float("SIMILARITY_THRESHOLD", 0.90)  # %90 ve üzeri = aynı haber
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
DUPLICATE_WINDOW_DAYS = _int("DUPLICATE_WINDOW_DAYS", 3)

# --- Coğrafi sabitler ----------------------------------------------------------
TIMEZONE = "Europe/Istanbul"
KOCAELI_CENTER = {"lat": 40.7654, "lng": 29.9408}  # İzmit (il merkezi)
KOCAELI_DEFAULT_ZOOM = 10
# Kocaeli'yi çevreleyen dikdörtgen; geocoding sonuçlarının doğrulanmasında kullanılır.
KOCAELI_BBOX = {"south": 40.48, "west": 29.30, "north": 41.25, "east": 30.45}
DISTRICTS = [
    "İzmit", "Gebze", "Darıca", "Çayırova", "Dilovası", "Körfez",
    "Derince", "Kartepe", "Başiskele", "Gölcük", "Karamürsel", "Kandıra",
]

# --- Flask -----------------------------------------------------------------
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = _int("FLASK_PORT", 5000)
