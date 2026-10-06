"""
ANA İŞLEM HATTI

Bir tarama çalışmasında her haber şu sırayla işlenir:

  scraping -> tarih kontrolü (son N gün) -> temizleme -> sınıflandırma
  -> Kocaeli kontrolü -> benzerlik (duplicate) kontrolü -> konum çıkarımı
  -> geocoding -> MongoDB'ye kayıt

Her linkin sonucu `processed_urls` koleksiyonuna yazılır:
  saved          : yeni haber olarak kaydedildi
  merged         : başka sitedeki aynı haberle birleştirildi (kaynak eklendi)
  no_category    : 5 haber türünden hiçbirine girmiyor
  not_local      : Kocaeli dışındaki bir olay
  no_location    : metinde konum bulunamadı -> haritada gösterilmez
  geocode_failed : konum koordinata çevrilemedi -> kayıt işlenmez
  no_date        : yayın tarihi okunamadı
  out_of_range   : seçilen zaman aralığından eski
  fetch_failed / parse_failed / geocode_error : geçici hata, sonra tekrar denenir

Komut satırından:
  python pipeline.py               # son 3 gün
  python pipeline.py --days 7      # son 7 gün
  python pipeline.py --reset       # işlenmiş link kayıtlarını silip baştan tara
"""
from __future__ import annotations

import argparse
import logging
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from pymongo.errors import DuplicateKeyError

import config
from db.mongo import get_db, init_indexes
from processing.classifier import classify
from processing.cleaner import build_article_text
from processing.dedup import DuplicateDetector, SentenceEmbedder, embedding_text
from processing.geocoder import GeocodingUnavailable, make_geocoder
from processing.location import LEVEL_NAMES, extract_location
from scraper.base import RawArticle, ScrapeItem
from scraper.sites import ALL_SCRAPERS
from utils.timeutils import as_utc, days_ago_utc, now_utc

log = logging.getLogger(__name__)

FINAL_STATUSES = {"saved", "merged", "no_category", "not_local", "no_location",
                  "geocode_failed", "no_date"}
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- durum bilgisi
class RunStatus:
    """Arayüzün 'tarama sürüyor' bilgisini gösterebilmesi için paylaşılan durum."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"running": False, "message": "", "started_at": None,
                       "finished_at": None, "days": None, "summary": None, "error": None}

    def update(self, **kwargs) -> None:
        with self._lock:
            self._state.update(kwargs)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)


STATUS = RunStatus()
_RUN_LOCK = threading.Lock()
_EMBEDDER: SentenceEmbedder | None = None


def shared_embedder() -> SentenceEmbedder:
    """Model ağır olduğu için tüm çalışmalarda tek örnek kullanılır."""
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceEmbedder()
    return _EMBEDDER


# ---------------------------------------------------------------- pipeline
class NewsPipeline:
    def __init__(self, db, scrapers=None, geocoder=None, embedder=None,
                 status: RunStatus | None = None):
        self.db = db
        self.scrapers = scrapers if scrapers is not None else [cls() for cls in ALL_SCRAPERS]
        self.geocoder = geocoder or make_geocoder(db)
        self.embedder = embedder or shared_embedder()
        self.dedup = DuplicateDetector(db)
        self.status = status or RunStatus()

    # ------------------------------------------------------------ link kontrolü
    def should_fetch(self, url: str, since) -> bool:
        if self.db.news.find_one({"sources.url": url}, {"_id": 1}):
            return False
        rec = self.db.processed_urls.find_one({"url": url})
        if not rec:
            return True
        status = rec.get("status")
        if status in FINAL_STATUSES:
            return False
        if status == "out_of_range":
            published = as_utc(rec.get("published_at"))
            return published is not None and published >= since
        if status in ("fetch_failed", "parse_failed"):
            return rec.get("attempts", 0) < MAX_ATTEMPTS
        return True  # geocode_error: servis düzelince tekrar denenir

    def mark(self, url: str, status: str, site_name: str, **extra) -> str:
        doc = {"url": url, "status": status, "site_name": site_name,
               "updated_at": now_utc(), **extra}
        self.db.processed_urls.update_one(
            {"url": url},
            {"$set": doc, "$inc": {"attempts": 1}, "$setOnInsert": {"first_seen": now_utc()}},
            upsert=True,
        )
        return status

    def _mark_both(self, raw: RawArticle, status: str, **extra) -> str:
        self.mark(raw.url, status, raw.site_name, title=raw.title,
                  published_at=raw.published_at, **extra)
        if raw.discovered_url and raw.discovered_url != raw.url:
            self.mark(raw.discovered_url, status, raw.site_name, canonical_url=raw.url,
                      title=raw.title, published_at=raw.published_at, **extra)
        return status

    # ------------------------------------------------------------ tek haber
    def process_item(self, item: ScrapeItem, since) -> str:
        if item.error_status:
            raw = item.article
            if raw is not None:
                return self._mark_both(raw, item.error_status, reason=item.error)
            return self.mark(item.url, item.error_status, item.site_name, reason=item.error)
        raw = item.article

        if raw.published_at < since:
            return self._mark_both(raw, "out_of_range")

        content = build_article_text(raw.title, raw.body_html, raw.ld_body, raw.description)
        if len(content) < 60:
            return self._mark_both(raw, "parse_failed", reason="haber metni bulunamadı")

        cls = classify(raw.title, content)
        if not cls.category:
            return self._mark_both(raw, "no_category", classification=cls.to_dict())

        loc = extract_location(raw.title, content)
        if not loc.is_local:
            return self._mark_both(raw, "not_local", foreign_places=loc.foreign_places[:5],
                                   local_score=loc.local_score, foreign_score=loc.foreign_score)

        embedding = self.embedder.encode(embedding_text(raw.title, content))
        duplicate, similarity = self.dedup.find_duplicate(embedding, raw.published_at)
        if duplicate is not None:
            self._merge(duplicate, raw, similarity)
            return self._mark_both(raw, "merged", duplicate_of=duplicate["_id"],
                                   similarity=round(similarity, 4))

        candidates = [c.to_dict() for c in loc.candidates]
        if not loc.found:
            return self._mark_both(raw, "no_location", type=cls.category)

        try:
            geo = self.geocoder.geocode_location(loc)
        except GeocodingUnavailable as exc:
            return self._mark_both(raw, "geocode_error", reason=str(exc))
        if not geo.success:
            return self._mark_both(raw, "geocode_failed", type=cls.category,
                                   location_candidates=candidates, geocode_attempts=geo.attempts)

        doc = self._build_document(raw, content, cls, loc, geo, embedding, candidates)
        try:
            inserted = self.db.news.insert_one(doc)
        except DuplicateKeyError:
            return self._mark_both(raw, "merged", reason="link zaten kayıtlı")
        return self._mark_both(raw, "saved", news_id=inserted.inserted_id)

    def _build_document(self, raw, content, cls, loc, geo, embedding, candidates) -> dict:
        result, query = geo.result, geo.query
        now = now_utc()
        return {
            # Proje dokümanındaki zorunlu alanlar
            "type": cls.category,
            "title": raw.title,
            "content": content,
            "location_text": query.query,
            "lat": result["lat"],
            "lng": result["lng"],
            "published_at": raw.published_at,
            "site_name": raw.site_name,
            "url": raw.url,
            # Aynı haberin yayınlandığı tüm kaynaklar
            "sources": [{"site_name": raw.site_name, "url": raw.url, "title": raw.title,
                         "published_at": raw.published_at, "similarity": 1.0}],
            # Konum ayrıntıları (sunumda "konumu nasıl buldun?" sorusu için)
            "district": loc.district or result.get("district"),
            "location": {
                "label": query.label,
                "level": query.level,
                "level_name": LEVEL_NAMES[query.level],
                "candidates": candidates,
                "geocode_query": query.query,
                "geocoder": self.geocoder.provider,
                "formatted_address": result.get("formatted_address"),
                "google_types": result.get("types"),
                "attempts": geo.attempts,
            },
            "geo": {"type": "Point", "coordinates": [result["lng"], result["lat"]]},
            "classification": cls.to_dict(),
            "embedding": embedding,
            "created_at": now,
            "updated_at": now,
        }

    def _merge(self, existing: dict, raw: RawArticle, similarity: float) -> None:
        if any(s.get("url") == raw.url for s in existing.get("sources", [])):
            return
        if any(s.get("site_name") == raw.site_name for s in existing.get("sources", [])):
            return  # aynı sitenin aynı haberi ikinci kez yayınlaması: kaynak listesini şişirme
        source = {"site_name": raw.site_name, "url": raw.url, "title": raw.title,
                  "published_at": raw.published_at, "similarity": round(similarity, 4)}
        try:
            self.db.news.update_one(
                {"_id": existing["_id"]},
                {"$push": {"sources": source}, "$set": {"updated_at": now_utc()}},
            )
        except DuplicateKeyError:
            pass

    # ------------------------------------------------------------ çalışma
    def run(self, days: int = config.SCRAPE_DAYS) -> dict:
        since = days_ago_utc(days)
        started = now_utc()
        self.status.update(running=True, started_at=started, finished_at=None, days=days,
                           message="Haber siteleri taranıyor", summary=None, error=None)

        def scrape_site(scraper):
            return scraper.scrape(
                since,
                should_fetch=lambda url: self.should_fetch(url, since),
                progress=lambda msg: self.status.update(message=msg),
            )

        with ThreadPoolExecutor(max_workers=len(self.scrapers) or 1) as pool:
            results = list(pool.map(scrape_site, self.scrapers))

        items = [item for site_items in results for item in site_items]
        # Eskiden yeniye işlenir: aynı haberin ilk yayınlayan kaynağı "ana kaynak" olur.
        items.sort(key=lambda i: (i.article.published_at if i.article and i.article.published_at
                                  else started))

        per_site: dict[str, Counter] = defaultdict(Counter)
        for n, item in enumerate(items, 1):
            self.status.update(message=f"Haberler işleniyor ({n}/{len(items)})")
            try:
                status = self.process_item(item, since)
            except Exception as exc:  # tek bir haberin hatası çalışmayı durdurmamalı
                log.exception("Haber işlenemedi: %s", item.url)
                status = self.mark(item.url, "parse_failed", item.site_name, reason=str(exc))
            per_site[item.site_name][status] += 1

        totals = Counter()
        for counter in per_site.values():
            totals.update(counter)
        summary = {
            "days": days,
            "since": since,
            "started_at": started,
            "finished_at": now_utc(),
            "totals": dict(totals),
            "per_site": {site: dict(c) for site, c in per_site.items()},
            "sites": [vars(s.report) for s in self.scrapers],
            "geocoding": {"provider": self.geocoder.provider, "api_calls": self.geocoder.api_calls,
                          "cache_hits": self.geocoder.cache_hits},
        }
        self.db.scrape_runs.insert_one(dict(summary))
        self.status.update(running=False, finished_at=summary["finished_at"],
                           message="Tarama tamamlandı", summary=_public_summary(summary))
        return summary


def _public_summary(summary: dict) -> dict:
    totals = summary["totals"]
    return {
        "saved": totals.get("saved", 0),
        "merged": totals.get("merged", 0),
        "skipped": sum(v for k, v in totals.items() if k not in ("saved", "merged")),
        "totals": totals,
    }


def run_safely(days: int = config.SCRAPE_DAYS, db=None) -> bool:
    """Aynı anda iki tarama çalışmasını engeller. Zamanlayıcı ve buton bunu çağırır."""
    if not _RUN_LOCK.acquire(blocking=False):
        return False
    try:
        database = db if db is not None else get_db()
        NewsPipeline(database, status=STATUS).run(days)
    except Exception as exc:
        log.exception("Tarama başarısız")
        STATUS.update(running=False, finished_at=now_utc(), error=str(exc),
                      message=f"Tarama başarısız: {exc}")
    finally:
        _RUN_LOCK.release()
    return True


def start_in_background(days: int, db=None) -> bool:
    if _RUN_LOCK.locked():
        return False
    STATUS.update(running=True, message="Tarama başlatılıyor", days=days, error=None)
    threading.Thread(target=run_safely, args=(days, db), daemon=True).start()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Kocaeli yerel haberlerini tara ve işle")
    parser.add_argument("--days", type=int, default=config.SCRAPE_DAYS, help="son kaç gün")
    parser.add_argument("--reset", action="store_true",
                        help="processed_urls kayıtlarını silip tüm linkleri yeniden değerlendir")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = get_db()
    init_indexes(db)
    if args.reset:
        deleted = db.processed_urls.delete_many({}).deleted_count
        print(f"{deleted} işlenmiş link kaydı silindi.")
    summary = NewsPipeline(db).run(args.days)
    print("\nSonuç:", summary["totals"])
    for site, counts in summary["per_site"].items():
        print(f"  {site}: {counts}")
    print("Geocoding:", summary["geocoding"])


if __name__ == "__main__":
    main()
