import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app import create_app
from pipeline import NewsPipeline
from processing.geocoder import Geocoder, GeocodingUnavailable, GoogleGeocoder
from scraper.base import RawArticle, ScrapeItem
from utils.text import normalize_for_matching

NOW = datetime.now(timezone.utc)


class FakeEmbedder:
    """Kelime torbası vektörü: aynı/çok benzer metinler ~1.0 benzerlik verir."""
    def encode(self, text):
        v = np.zeros(256, dtype=np.float32)
        for w in normalize_for_matching(text).split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
        return (v / (np.linalg.norm(v) or 1)).tolist()


class FakeGeocoder(GoogleGeocoder):
    """Google yerine sabit cevaplar. Önbellek ve doğrulama mantığı gerçek sınıftan gelir."""
    ANSWERS = {
        "yenişehir mahallesi, izmit, kocaeli": {"lat": 40.77, "lng": 29.93, "types": ["neighborhood"],
                                               "province": "Kocaeli", "district": "İzmit",
                                               "formatted_address": "Yenişehir, İzmit/Kocaeli"},
        "izmit, kocaeli": {"lat": 40.7654, "lng": 29.9408, "types": ["locality"],
                           "province": "Kocaeli", "district": "İzmit"},
        "gebze, kocaeli": {"lat": 40.80, "lng": 29.43, "types": ["locality"],
                           "province": "Kocaeli", "district": "Gebze"},
    }

    def __init__(self, db, fail=False):
        super().__init__(db, api_key="test")
        self.fail = fail

    def _call_api(self, query):
        if self.fail:
            raise GeocodingUnavailable("kota")
        self.api_calls += 1
        return self.ANSWERS.get(self.cache_key(query))


def make_item(site, url, title, body, hours_ago=5):
    art = RawArticle(url=url, site_name=site, title=title, published_at=NOW - timedelta(hours=hours_ago),
                     body_html=f"<p>{body}</p>")
    return ScrapeItem(url, site, article=art)


ACCIDENT = ("Kocaeli'nin İzmit ilçesi Yenişehir Mahallesi'nde iki otomobil çarpıştı. Kazada maddi hasar "
            "oluştu, sürücüler hafif yaralandı ve hastaneye kaldırıldı.")


@pytest.fixture
def pipeline(db):
    return NewsPipeline(db, scrapers=[], geocoder=FakeGeocoder(db), embedder=FakeEmbedder())


def test_saves_news_with_all_required_fields(pipeline, db):
    status = pipeline.process_item(make_item("Ses Kocaeli", "https://a/1", "İzmit'te kaza", ACCIDENT), NOW - timedelta(days=3))
    assert status == "saved"
    doc = db.news.find_one()
    for field in ("type", "title", "content", "location_text", "lat", "lng", "published_at", "site_name", "url"):
        assert doc[field] not in (None, "")
    assert doc["type"] == "Trafik Kazası"
    assert doc["location_text"] == "Yenişehir Mahallesi, İzmit, Kocaeli"
    assert doc["location"]["candidates"]


def test_same_story_on_other_site_is_merged(pipeline, db):
    since = NOW - timedelta(days=3)
    pipeline.process_item(make_item("Ses Kocaeli", "https://a/1", "İzmit'te kaza", ACCIDENT), since)
    status = pipeline.process_item(make_item("Bizim Yaka", "https://b/9", "İzmit'te kaza", ACCIDENT, 4), since)
    assert status == "merged"
    assert db.news.count_documents({}) == 1
    sources = db.news.find_one()["sources"]
    assert [s["site_name"] for s in sources] == ["Ses Kocaeli", "Bizim Yaka"]
    assert sources[1]["similarity"] >= 0.90


def test_same_url_is_not_fetched_again(pipeline, db):
    since = NOW - timedelta(days=3)
    pipeline.process_item(make_item("Ses Kocaeli", "https://a/1", "İzmit'te kaza", ACCIDENT), since)
    assert pipeline.should_fetch("https://a/1", since) is False


def test_skip_reasons_are_recorded(pipeline, db):
    since = NOW - timedelta(days=3)
    cases = {
        "no_category": make_item("Ses Kocaeli", "https://a/2", "Meclis toplandı",
                                 "Belediye meclisi bütçe görüşmelerini tamamladı ve oylamaya geçti."),
        "not_local": make_item("Ses Kocaeli", "https://a/3", "Bursa'da yangın",
                               "Bursa'nın Kestel ilçesinde çıkan yangın itfaiye ekiplerince söndürüldü, ev küle döndü."),
        "no_location": make_item("Ses Kocaeli", "https://a/4", "Hırsızlar yakalandı",
                                 "Polis, evlerden ziynet eşyası çalan hırsızlık şüphelilerini yakaladı."),
        "out_of_range": make_item("Ses Kocaeli", "https://a/5", "Eski kaza", ACCIDENT, hours_ago=24 * 10),
    }
    for expected, item in cases.items():
        assert pipeline.process_item(item, since) == expected
        assert db.processed_urls.find_one({"url": item.url})["status"] == expected
    assert db.news.count_documents({}) == 0


def test_geocode_failure_is_not_saved_and_cache_prevents_repeat_calls(db):
    p = NewsPipeline(db, scrapers=[], geocoder=FakeGeocoder(db), embedder=FakeEmbedder())
    body = "Kocaeli'nin Kandıra ilçesi Bilinmeyen Mahallesi'nde bir evde çıkan yangın söndürüldü, ev küle döndü."
    assert p.process_item(make_item("Ses Kocaeli", "https://a/6", "Kandıra'da yangın", body), NOW - timedelta(days=3)) == "geocode_failed"
    calls = p.geocoder.api_calls
    p.geocoder._memory.clear()                       # bellek önbelleği boş, Mongo önbelleği dolu
    p.geocoder.geocode_location(__import__("processing.location", fromlist=["x"]).extract_location("Kandıra'da yangın", body))
    assert p.geocoder.api_calls == calls             # tekrar API çağrısı yapılmadı
    assert db.news.count_documents({}) == 0


def test_transient_geocoding_error_is_retryable(db):
    p = NewsPipeline(db, scrapers=[], geocoder=FakeGeocoder(db, fail=True), embedder=FakeEmbedder())
    since = NOW - timedelta(days=3)
    assert p.process_item(make_item("Ses Kocaeli", "https://a/7", "İzmit'te kaza", ACCIDENT), since) == "geocode_error"
    assert p.should_fetch("https://a/7", since) is True
    assert db.geocache.count_documents({}) == 0      # geçici hata önbelleğe yazılmaz


def test_geocoder_validation_rules():
    ok = {"lat": 40.77, "lng": 29.93, "types": ["neighborhood"], "province": "Kocaeli", "district": "Izmit"}
    assert Geocoder.validate(ok, 3, "İzmit")[0] is True                       # İzmit == Izmit
    assert Geocoder.validate({**ok, "province": "Sakarya"}, 3, None)[0] is False
    assert Geocoder.validate({**ok, "lat": 39.9}, 3, None)[0] is False         # sınır dışı
    assert Geocoder.validate({**ok, "types": ["locality"]}, 3, None)[0] is False   # mahalle istendi, ilçe döndü
    assert Geocoder.validate({**ok, "types": ["locality"]}, 1, None)[0] is True
    assert Geocoder.validate({**ok, "district": "Gebze"}, 3, "İzmit")[0] is False


def test_api_filters(pipeline, db):
    since = NOW - timedelta(days=3)
    pipeline.process_item(make_item("Ses Kocaeli", "https://a/1", "İzmit'te kaza", ACCIDENT), since)
    pipeline.process_item(make_item(
        "Özgür Kocaeli", "https://c/1", "Gebze'de elektrik kesintisi",
        "SEDAŞ, Gebze ilçesinde yarın planlı elektrik kesintisi yapılacağını, bölgede elektrik verilemeyeceğini duyurdu."), since)
    client = create_app(db).test_client()

    all_items = client.get("/api/news").get_json()
    assert all_items["count"] == 2
    assert "embedding" not in all_items["items"][0]

    only_power = client.get("/api/news?types=Elektrik Kesintisi").get_json()
    assert [i["type"] for i in only_power["items"]] == ["Elektrik Kesintisi"]

    assert client.get("/api/news?types=").get_json()["count"] == 0
    assert client.get("/api/news?district=Gebze").get_json()["count"] == 1
    today = datetime.now().date()
    old = (today - timedelta(days=30)).isoformat()
    assert client.get(f"/api/news?start={old}&end={old}").get_json()["count"] == 0

    stats = client.get("/api/stats?district=İzmit").get_json()
    assert stats["counts"]["Trafik Kazası"] == 1 and stats["counts"]["Elektrik Kesintisi"] == 0

    detail_id = all_items["items"][0]["id"]
    detail = client.get(f"/api/news/{detail_id}").get_json()
    assert "classification" in detail and "content" in detail
    assert client.get("/api/news/gecersiz").status_code == 404


def test_index_page_renders_without_keys(db):
    client = create_app(db).test_client()
    html = client.get("/").get_data(as_text=True)
    assert "Kocaeli Haber Haritası" in html and "APP_CONFIG" in html


def test_index_loads_correct_map_library(db, monkeypatch):
    import config
    monkeypatch.setattr(config, "MAP_PROVIDER", "osm")
    html = create_app(db).test_client().get("/").get_data(as_text=True)
    assert "leaflet" in html and "maps.googleapis.com" not in html
    assert '"mapProvider": "osm"' in html and "Geçici harita" in html

    monkeypatch.setattr(config, "MAP_PROVIDER", "google")
    monkeypatch.setattr(config, "GOOGLE_MAPS_JS_API_KEY", "TEST_KEY")
    html = create_app(db).test_client().get("/").get_data(as_text=True)
    assert "maps.googleapis.com" in html and "leaflet.min.js" not in html


def test_reclassify_tool_updates_and_removes(pipeline, db):
    from tools.reclassify import apply_changes, evaluate
    since = NOW - timedelta(days=3)
    pipeline.process_item(make_item("Ses Kocaeli", "https://a/1", "İzmit'te kaza", ACCIDENT), since)
    doc = db.news.find_one()
    # Eski kurallarla yanlış kaydedilmiş bir haber taklidi:
    db.news.update_one({"_id": doc["_id"]}, {"$set": {"type": "Kültürel Etkinlikler"}})
    db.news.insert_one({**{k: v for k, v in doc.items() if k != "_id"}, "title": "Uyuşturucu operasyonu",
                        "content": "Operasyonda şüpheliler gözaltına alındı ve tutuklandı.",
                        "type": "Hırsızlık", "sources": [{"site_name": "Bizim Yaka", "url": "https://b/2"}]})

    rows = evaluate(db)
    stats = apply_changes(db, rows)
    assert stats == {"türü değişti": 1, "silindi": 1}
    assert db.news.find_one()["type"] == "Trafik Kazası"
    assert db.news.count_documents({}) == 1
    assert db.processed_urls.find_one({"url": "https://b/2"})["status"] == "no_category"
