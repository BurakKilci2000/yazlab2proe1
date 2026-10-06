"""
MongoDB bağlantısı ve koleksiyon indeksleri.

Koleksiyonlar:
  news            -> Haritada gösterilen, işlenmiş haberler
  processed_urls  -> İncelenen her haber linkinin sonucu (kaydedildi, birleştirildi,
                     kategori yok, konum yok...). Aynı linkin tekrar tekrar
                     işlenmesini önler ve sunumda "neden atlandı?" sorusunu cevaplar.
  geocache        -> Geocoding önbelleği (aynı adres için tekrar API çağrısı yapılmaz;
                     servis adıyla birlikte saklanır: google / nominatim)
  scrape_runs     -> Her tarama çalışmasının özeti
"""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

import config

_client: MongoClient | None = None


def get_db() -> Database:
    global _client
    if _client is None:
        _client = MongoClient(
            config.MONGO_URI,
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )
    return _client[config.MONGO_DB_NAME]


def ping(db: Database) -> bool:
    try:
        db.client.admin.command("ping")
        return True
    except Exception:
        return False


def init_indexes(db: Database) -> None:
    # Duplicate kontrolünün veritabanı seviyesindeki garantisi:
    # Bir haber linki, news koleksiyonunda en fazla bir belgede bulunabilir.
    db.news.create_index([("sources.url", ASCENDING)], unique=True, name="uniq_source_url")
    db.news.create_index([("published_at", DESCENDING)], name="published_at")
    db.news.create_index([("type", ASCENDING), ("published_at", DESCENDING)], name="type_date")
    db.news.create_index([("district", ASCENDING)], name="district")

    db.processed_urls.create_index([("url", ASCENDING)], unique=True, name="uniq_url")
    db.processed_urls.create_index([("status", ASCENDING)], name="status")

    # Önbellek anahtarı = servis + sorgu (Google ve Nominatim sonuçları karışmaz).
    if "uniq_query" in db.geocache.index_information():   # eski sürümden kalan indeks
        db.geocache.drop_index("uniq_query")
    db.geocache.create_index([("provider", ASCENDING), ("query", ASCENDING)],
                             unique=True, name="uniq_provider_query")
    db.scrape_runs.create_index([("started_at", DESCENDING)], name="started_at")
