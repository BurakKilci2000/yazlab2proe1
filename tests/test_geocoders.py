import pytest

import config
from processing.geocoder import (GeocodingUnavailable, GoogleGeocoder, NominatimGeocoder,
                                 make_geocoder)
from processing.location import extract_location

# Nominatim jsonv2 + addressdetails cevabının biçimi
YENISEHIR = {
    "osm_type": "relation", "osm_id": 1234567, "lat": "40.7712", "lon": "29.9301",
    "category": "boundary", "type": "administrative", "addresstype": "suburb",
    "display_name": "Yenişehir Mahallesi, İzmit, Kocaeli, Marmara Bölgesi, 41040, Türkiye",
    "address": {"suburb": "Yenişehir Mahallesi", "town": "İzmit", "province": "Kocaeli",
                "ISO3166-2-lvl4": "TR-41", "region": "Marmara Bölgesi", "country": "Türkiye"},
}
IZMIT = {
    "osm_type": "relation", "osm_id": 7654321, "lat": "40.7654", "lon": "29.9408",
    "category": "boundary", "type": "administrative", "addresstype": "town",
    "display_name": "İzmit, Kocaeli, Türkiye",
    "address": {"town": "İzmit", "province": "Kocaeli", "ISO3166-2-lvl4": "TR-41"},
}


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, answers, status=200):
        self.answers = answers          # sorgu -> liste
        self.status = status
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return FakeResponse(self.status, self.answers.get(params["q"], []))


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(config, "NOMINATIM_MIN_INTERVAL", 0)


def test_parse_osm_result():
    r = NominatimGeocoder.parse(YENISEHIR)
    assert (r["lat"], r["lng"]) == (40.7712, 29.9301)
    assert r["province"] == "Kocaeli" and r["district"] == "İzmit" and r["level"] == 3
    assert NominatimGeocoder.validate(r, 3, "İzmit") == (True, "ok")


def test_district_level_result_rejected_for_neighbourhood_query():
    r = NominatimGeocoder.parse(IZMIT)
    assert r["level"] == 1
    assert NominatimGeocoder.validate(r, 3, "İzmit")[0] is False      # mahalle istendi
    assert NominatimGeocoder.validate(r, 1, "İzmit")[0] is True       # ilçe istendi


def test_request_follows_usage_policy_and_falls_back(db):
    session = FakeSession({"İzmit, Kocaeli": [IZMIT]})
    g = NominatimGeocoder(db, email="ogrenci@example.com", session=session)
    loc = extract_location("Kaza", "Kocaeli'nin İzmit ilçesi Bilinmeyen Mahallesi'nde kaza oldu.")
    outcome = g.geocode_location(loc)

    assert outcome.success and outcome.query.query == "İzmit, Kocaeli"   # mahalle bulunamadı -> ilçe
    assert [a["ok"] for a in outcome.attempts] == [False, True]
    params = session.calls[0]
    assert params["bounded"] == 1 and params["countrycodes"] == "tr" and params["limit"] == 1
    assert "KocaeliHaberHaritasi" in session.headers["User-Agent"]


def test_cache_is_per_provider(db):
    session = FakeSession({"İzmit, Kocaeli": [IZMIT]})
    g = NominatimGeocoder(db, session=session)
    g.lookup("İzmit, Kocaeli")
    g._memory.clear()
    g.lookup("İzmit, Kocaeli")
    assert len(session.calls) == 1                      # ikinci sorgu önbellekten
    assert db.geocache.find_one({"provider": "nominatim"}) is not None
    assert db.geocache.find_one({"provider": "google"}) is None


def test_rate_limit_or_block_is_temporary(db):
    g = NominatimGeocoder(db, session=FakeSession({}, status=429))
    with pytest.raises(GeocodingUnavailable):
        g.lookup("İzmit, Kocaeli")
    assert db.geocache.count_documents({}) == 0         # geçici hata önbelleğe yazılmaz


def test_google_without_key_is_temporary_error(db):
    with pytest.raises(GeocodingUnavailable):
        GoogleGeocoder(db, api_key="").lookup("İzmit, Kocaeli")


def test_provider_selection(monkeypatch, db):
    monkeypatch.delenv("GEOCODER", raising=False)
    assert config._provider("GEOCODER", "", ("google", "nominatim")) == "nominatim"
    assert config._provider("GEOCODER", "AIza...", ("google", "nominatim")) == "google"
    monkeypatch.setenv("GEOCODER", "nominatim")
    assert config._provider("GEOCODER", "AIza...", ("google", "nominatim")) == "nominatim"
    assert isinstance(make_geocoder(db, "nominatim"), NominatimGeocoder)
    assert isinstance(make_geocoder(db, "google"), GoogleGeocoder)
