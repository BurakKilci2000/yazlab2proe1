"""
GEOCODING (Proje dokümanı Bölüm 7)

Doküman "bir geocoding servisi (Google Geocoding API gibi)" kullanılmasını ister.
İki servis desteklenir, hangisinin kullanılacağı .env içindeki GEOCODER ayarıyla
seçilir (bkz. config.py):

  GoogleGeocoder     Google Geocoding API. Anahtar .env dosyasında durur,
                     koda yazılmaz ve tarayıcıya hiçbir zaman gönderilmez.
  NominatimGeocoder  OpenStreetMap Nominatim. Ücretsizdir, anahtar gerektirmez.
                     Kullanım kuralı: saniyede en fazla 1 istek + önbellek.

İki servis de aynı ortak sınıftan (Geocoder) türer; yalnızca "API'yi çağır ve
cevabı ortak biçime çevir" kısmı farklıdır. Ortak sınıfın sağladıkları:

- Önbellek: Her sorgunun sonucu MongoDB'deki `geocache` koleksiyonuna
  (servis adıyla birlikte) yazılır. Aynı adres tekrar sorulduğunda API'ye
  gidilmez. Bulunamayan adresler de önbelleğe yazılır. Geçici hatalar (kota,
  ağ hatası, geçersiz anahtar) önbelleğe yazılmaz, sonra tekrar denenir.
- Doğrulama: Sonuç Kocaeli dikdörtgeni içinde olmalı, il "Kocaeli" olmalı,
  ilçe biliniyorsa eşleşmeli ve sonuç istenen seviyeye yeterince yakın olmalı
  (ör. mahalle sorgusuna sadece "İzmit" dönerse kabul edilmez, bir sonraki
  daha genel sorguya geçilir).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

import requests

import config
from processing.location import LEVEL_NAMES, GeocodeQuery, LocationResult
from utils.text import ascii_fold, turkish_lower
from utils.timeutils import now_utc

log = logging.getLogger(__name__)

# Seviye ölçeği (location.py ile aynı): 5 adres, 4 cadde/yer, 3 mahalle, 2 yol/bölge,
# 1 ilçe, 0 il ve üstü.
_GOOGLE_TYPE_LEVELS = {
    "street_address": 5, "premise": 5, "subpremise": 5,
    "route": 4, "intersection": 4, "establishment": 4, "point_of_interest": 4,
    "park": 4, "transit_station": 4, "airport": 4, "stadium": 4,
    "neighborhood": 3, "sublocality": 3, "sublocality_level_1": 3, "sublocality_level_2": 3,
    "administrative_area_level_3": 3, "administrative_area_level_4": 3,
    "administrative_area_level_5": 3,
    "natural_feature": 2, "colloquial_area": 2, "postal_code": 2,
    "locality": 1, "administrative_area_level_2": 1,
    "administrative_area_level_1": 0, "country": 0,
}
_OSM_TYPE_LEVELS = {
    "house": 5, "building": 5,
    "road": 4,
    "neighbourhood": 3, "quarter": 3, "suburb": 3, "village": 3, "hamlet": 3,
    "isolated_dwelling": 3, "allotments": 3,
    "town": 1, "city": 1, "county": 1, "municipality": 1, "city_district": 1, "district": 1,
    "province": 0, "state": 0, "region": 0, "country": 0, "postcode": 2,
}


class GeocodingUnavailable(Exception):
    """Servise şu an ulaşılamıyor (anahtar yok, kota, ağ). Tekrar denenebilir."""


def result_level(types: list[str]) -> int:
    return max((_GOOGLE_TYPE_LEVELS.get(t, 0) for t in types), default=0)


# ===================================================================== ortak sınıf
class Geocoder:
    provider = "base"

    def __init__(self, db, session: requests.Session | None = None):
        self.db = db
        self.session = session or requests.Session()
        self._memory: dict[str, dict | None] = {}
        self._lock = threading.Lock()
        self.api_calls = 0
        self.cache_hits = 0

    @staticmethod
    def cache_key(query: str) -> str:
        return " ".join(turkish_lower(query).split())

    def _call_api(self, query: str) -> dict | None:
        """Alt sınıflar uygular. Ortak biçimde sözlük ya da bulunamadıysa None döner:
        {lat, lng, formatted_address, types, level, province, district, place_id}"""
        raise NotImplementedError

    # ------------------------------------------------------------ önbellek
    def lookup(self, query: str) -> dict | None:
        key = self.cache_key(query)
        with self._lock:
            if key in self._memory:
                self.cache_hits += 1
                return self._memory[key]
        cached = self.db.geocache.find_one({"provider": self.provider, "query": key})
        if cached is not None:
            self.cache_hits += 1
            result = cached.get("result")
        else:
            result = self._call_api(query)   # GeocodingUnavailable yukarı iletilir
            self.db.geocache.update_one(
                {"provider": self.provider, "query": key},
                {"$set": {"provider": self.provider, "query": key, "raw_query": query,
                          "result": result, "created_at": now_utc()}},
                upsert=True,
            )
        with self._lock:
            self._memory[key] = result
        return result

    # ------------------------------------------------------------ doğrulama
    @staticmethod
    def validate(result: dict | None, requested_level: int, district: str | None) -> tuple[bool, str]:
        if not result:
            return False, "sonuç yok"
        b = config.KOCAELI_BBOX
        if not (b["south"] <= result["lat"] <= b["north"] and b["west"] <= result["lng"] <= b["east"]):
            return False, "Kocaeli sınırları dışında"
        if ascii_fold(result.get("province") or "") != "kocaeli":
            return False, f"il Kocaeli değil ({result.get('province')})"
        if district and result.get("district") and \
                ascii_fold(result["district"]) != ascii_fold(district):
            return False, f"ilçe uyuşmuyor ({result['district']})"
        level = result.get("level")
        if level is None:
            level = result_level(result.get("types", []))
        if requested_level >= 2 and level < 2:
            return False, "sonuç istenen konumdan çok genel"
        if level < 1:
            return False, "sonuç il seviyesinde"
        return True, "ok"

    def geocode_location(self, loc: LocationResult) -> "GeocodeOutcome":
        """Sorguları en spesifikten genele dener. İlk geçerli sonucu döndürür."""
        outcome = GeocodeOutcome()
        for q in loc.queries:
            result = self.lookup(q.query)
            ok, reason = self.validate(result, q.level, loc.district)
            outcome.attempts.append(
                {"query": q.query, "level": LEVEL_NAMES[q.level], "ok": ok, "reason": reason}
            )
            if ok:
                outcome.query, outcome.result = q, result
                break
        return outcome


@dataclass
class GeocodeOutcome:
    query: GeocodeQuery | None = None
    result: dict | None = None
    attempts: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.result is not None


# ===================================================================== Google
class GoogleGeocoder(Geocoder):
    provider = "google"
    API_URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, db, api_key: str = config.GOOGLE_GEOCODING_API_KEY,
                 session: requests.Session | None = None):
        super().__init__(db, session)
        self.api_key = api_key

    def _call_api(self, query: str) -> dict | None:
        if not self.api_key:
            raise GeocodingUnavailable("GOOGLE_GEOCODING_API_KEY .env dosyasında tanımlı değil")
        bbox = config.KOCAELI_BBOX
        params = {
            "address": query,
            "key": self.api_key,
            "language": "tr",
            "region": "tr",
            "components": "country:TR",
            "bounds": f"{bbox['south']},{bbox['west']}|{bbox['north']},{bbox['east']}",
        }
        try:
            r = self.session.get(self.API_URL, params=params, timeout=15)
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            raise GeocodingUnavailable(f"Geocoding isteği başarısız: {exc}") from exc
        self.api_calls += 1

        status = data.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            raise GeocodingUnavailable(f"Geocoding API: {status} {data.get('error_message', '')}".strip())

        best = data["results"][0]
        comps = best.get("address_components", [])

        def comp(kind: str) -> str | None:
            return next((c["long_name"] for c in comps if kind in c.get("types", [])), None)

        loc = best["geometry"]["location"]
        types = best.get("types", [])
        return {
            "lat": loc["lat"],
            "lng": loc["lng"],
            "formatted_address": best.get("formatted_address"),
            "types": types,
            "level": result_level(types),
            "province": comp("administrative_area_level_1"),
            "district": comp("administrative_area_level_2"),
            "place_id": best.get("place_id"),
        }


# ===================================================================== Nominatim
class NominatimGeocoder(Geocoder):
    provider = "nominatim"

    # Nominatim'in kuralı tüm uygulama için geçerlidir; bu yüzden kilit sınıf düzeyinde.
    _rate_lock = threading.Lock()
    _last_request = 0.0

    def __init__(self, db, url: str = config.NOMINATIM_URL, email: str = config.NOMINATIM_EMAIL,
                 session: requests.Session | None = None):
        super().__init__(db, session)
        self.url = url
        self.email = email
        contact = f" ({email})" if email else ""
        self.session.headers.update({
            "User-Agent": f"KocaeliHaberHaritasi/1.0 ders-projesi{contact}",
            "Accept-Language": "tr",
        })

    def _wait_turn(self) -> None:
        cls = NominatimGeocoder
        with cls._rate_lock:
            elapsed = time.monotonic() - cls._last_request
            if elapsed < config.NOMINATIM_MIN_INTERVAL:
                time.sleep(config.NOMINATIM_MIN_INTERVAL - elapsed)
            cls._last_request = time.monotonic()

    @staticmethod
    def _find_district(address: dict) -> str | None:
        """OSM adres alanlarında Kocaeli ilçelerinden birini arar."""
        folded = {ascii_fold(d): d for d in config.DISTRICTS}
        for key in ("town", "county", "city_district", "municipality", "city", "district"):
            value = address.get(key)
            if value and ascii_fold(value) in folded:
                return folded[ascii_fold(value)]
        return address.get("town") or address.get("county")

    @staticmethod
    def _find_province(address: dict) -> str | None:
        if address.get("ISO3166-2-lvl4") == "TR-41":       # Kocaeli'nin plaka/ISO kodu
            return "Kocaeli"
        return address.get("province") or address.get("state")

    @classmethod
    def parse(cls, item: dict) -> dict:
        address = item.get("address", {})
        addresstype = item.get("addresstype") or item.get("type") or ""
        level = _OSM_TYPE_LEVELS.get(addresstype, 4)   # bilinmeyen tipler: yer (POI)
        return {
            "lat": float(item["lat"]),
            "lng": float(item["lon"]),
            "formatted_address": item.get("display_name"),
            "types": [f"osm:{item.get('category', '')}:{addresstype}"],
            "level": level,
            "province": cls._find_province(address),
            "district": cls._find_district(address),
            "place_id": f"osm:{item.get('osm_type', '')}/{item.get('osm_id', '')}",
        }

    def _call_api(self, query: str) -> dict | None:
        bbox = config.KOCAELI_BBOX
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
            "countrycodes": "tr",
            "accept-language": "tr",
            # Arama Kocaeli dikdörtgeniyle sınırlandırılır.
            "viewbox": f"{bbox['west']},{bbox['north']},{bbox['east']},{bbox['south']}",
            "bounded": 1,
        }
        if self.email:
            params["email"] = self.email
        self._wait_turn()
        try:
            r = self.session.get(self.url, params=params, timeout=20)
        except requests.RequestException as exc:
            raise GeocodingUnavailable(f"Nominatim isteği başarısız: {exc}") from exc
        if r.status_code in (403, 429, 503):
            raise GeocodingUnavailable(f"Nominatim isteği reddetti (HTTP {r.status_code})")
        if r.status_code != 200:
            raise GeocodingUnavailable(f"Nominatim HTTP {r.status_code}")
        try:
            data = r.json()
        except ValueError as exc:
            raise GeocodingUnavailable("Nominatim geçersiz cevap döndürdü") from exc
        self.api_calls += 1
        return self.parse(data[0]) if data else None


def make_geocoder(db, provider: str = config.GEOCODER) -> Geocoder:
    """Ayarlardaki servise göre geocoder oluşturur."""
    if provider == "google":
        return GoogleGeocoder(db)
    return NominatimGeocoder(db)
