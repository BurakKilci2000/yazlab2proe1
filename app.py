"""
WEB UYGULAMASI (Flask)

Sayfa:
  GET  /                      Harita arayüzü
API (arayüz bunları fetch ile çağırır, sayfa yeniden yüklenmez):
  GET  /api/news              Filtrelenmiş haberler  ?types=Yangın,Hırsızlık&district=İzmit
                                                     &start=2026-04-01&end=2026-04-03
  GET  /api/news/<id>         Tek haber + konum/sınıflandırma ayrıntıları
  GET  /api/stats             Aynı filtrelerle tür başına haber sayısı
  POST /api/scrape            Taramayı elle başlat   {"days": 3}
  GET  /api/scrape/status     Taramanın durumu

Çalıştırma:  python app.py   ->  http://127.0.0.1:5000
Uygulama açılınca zamanlayıcı da başlar; tarama otomatik olarak belirli
aralıklarla (varsayılan 60 dk) ve açılışta bir kez çalışır.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from bson import ObjectId
from bson.errors import InvalidId
from flask import Flask, abort, jsonify, render_template, request

import config
import pipeline
from db.mongo import get_db, init_indexes, ping
from processing.classifier import CATEGORIES
from utils.timeutils import local_day_range_to_utc, now_utc, parse_local_date, to_iso

log = logging.getLogger(__name__)

# Haritadaki işaretlerin renk ve sembolleri (Şekil 1'deki örneğe uygun)
TYPE_STYLES = [
    {"name": "Trafik Kazası", "slug": "trafik", "color": "#D7263D", "glyph": "#FFFFFF"},
    {"name": "Yangın", "slug": "yangin", "color": "#F26419", "glyph": "#FFFFFF"},
    {"name": "Elektrik Kesintisi", "slug": "elektrik", "color": "#25283D", "glyph": "#FFD23F"},
    {"name": "Hırsızlık", "slug": "hirsizlik", "color": "#6B3FA0", "glyph": "#FFFFFF"},
    {"name": "Kültürel Etkinlikler", "slug": "kultur", "color": "#1B998B", "glyph": "#FFFFFF"},
]

LIST_PROJECTION = {"embedding": 0, "content": 0, "classification": 0, "geo": 0}


def build_filter(args, include_types: bool = True) -> dict | None:
    """URL parametrelerinden MongoDB sorgusu üretir. Boş sonuç gerekiyorsa None döner."""
    query: dict = {"lat": {"$ne": None}, "lng": {"$ne": None}}

    if include_types and "types" in args:
        types = [t.strip() for t in args.get("types", "").split(",") if t.strip() in CATEGORIES]
        if not types:
            return None            # hiçbir tür seçili değil
        query["type"] = {"$in": types}

    district = (args.get("district") or "").strip()
    if district:
        if district not in config.DISTRICTS:
            return None
        query["district"] = district

    start_utc, end_utc = local_day_range_to_utc(parse_local_date(args.get("start")),
                                                parse_local_date(args.get("end")))
    if start_utc or end_utc:
        query["published_at"] = {}
        if start_utc:
            query["published_at"]["$gte"] = start_utc
        if end_utc:
            query["published_at"]["$lt"] = end_utc
    return query


def serialize(doc: dict, detail: bool = False) -> dict:
    loc = doc.get("location", {})
    data = {
        "id": str(doc["_id"]),
        "type": doc.get("type"),
        "title": doc.get("title"),
        "published_at": to_iso(doc.get("published_at")),
        "site_name": doc.get("site_name"),
        "url": doc.get("url"),
        "sources": [
            {"site_name": s.get("site_name"), "url": s.get("url"),
             "published_at": to_iso(s.get("published_at")), "similarity": s.get("similarity")}
            for s in doc.get("sources", [])
        ],
        "location_text": doc.get("location_text"),
        "district": doc.get("district"),
        "lat": doc.get("lat"),
        "lng": doc.get("lng"),
        "location": {
            "label": loc.get("label"),
            "level_name": loc.get("level_name"),
            "candidates": loc.get("candidates", []),
            "formatted_address": loc.get("formatted_address"),
        },
    }
    if detail:
        data["content"] = doc.get("content")
        data["classification"] = doc.get("classification")
        data["location"]["attempts"] = loc.get("attempts", [])
        data["location"]["geocode_query"] = loc.get("geocode_query")
    return data


def last_run(db) -> dict | None:
    doc = db.scrape_runs.find_one(sort=[("started_at", -1)])
    if not doc:
        return None
    totals = doc.get("totals", {})
    return {
        "finished_at": to_iso(doc.get("finished_at")),
        "days": doc.get("days"),
        "saved": totals.get("saved", 0),
        "merged": totals.get("merged", 0),
        "totals": totals,
    }


def create_app(db=None) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    database = db if db is not None else get_db()

    @app.get("/")
    def index():
        app_config = {
            "center": config.KOCAELI_CENTER,
            "zoom": config.KOCAELI_DEFAULT_ZOOM,
            "mapId": config.GOOGLE_MAPS_MAP_ID,
            "types": TYPE_STYLES,
            "districts": config.DISTRICTS,
            "defaultDays": config.SCRAPE_DAYS,
            "hasMapsKey": bool(config.GOOGLE_MAPS_JS_API_KEY),
            "mapProvider": config.MAP_PROVIDER,
        }
        return render_template("index.html", app_config=app_config,
                               map_provider=config.MAP_PROVIDER,
                               maps_key=config.GOOGLE_MAPS_JS_API_KEY,
                               districts=config.DISTRICTS)

    @app.get("/api/news")
    def api_news():
        query = build_filter(request.args)
        if query is None:
            return jsonify({"count": 0, "items": []})
        limit = min(max(request.args.get("limit", 500, type=int), 1), 2000)
        cursor = database.news.find(query, LIST_PROJECTION).sort("published_at", -1).limit(limit)
        items = [serialize(d) for d in cursor]
        return jsonify({"count": len(items), "items": items})

    @app.get("/api/news/<news_id>")
    def api_news_detail(news_id: str):
        try:
            oid = ObjectId(news_id)
        except (InvalidId, TypeError):
            abort(404)
        doc = database.news.find_one({"_id": oid}, {"embedding": 0})
        if not doc:
            abort(404)
        return jsonify(serialize(doc, detail=True))

    @app.get("/api/stats")
    def api_stats():
        query = build_filter(request.args, include_types=False)
        counts = {t["name"]: 0 for t in TYPE_STYLES}
        if query is not None:
            for name in counts:
                counts[name] = database.news.count_documents({**query, "type": name})
        return jsonify({"counts": counts, "total": sum(counts.values())})

    @app.post("/api/scrape")
    def api_scrape():
        payload = request.get_json(silent=True) or {}
        try:
            days = int(payload.get("days", config.SCRAPE_DAYS))
        except (TypeError, ValueError):
            days = config.SCRAPE_DAYS
        days = min(max(days, 1), 30)
        started = pipeline.start_in_background(days, database)
        if not started:
            return jsonify({"started": False, "message": "Bir tarama zaten sürüyor"}), 409
        return jsonify({"started": True, "days": days}), 202

    @app.get("/api/scrape/status")
    def api_scrape_status():
        state = pipeline.STATUS.snapshot()
        return jsonify({
            "running": state["running"],
            "message": state["message"],
            "error": state["error"],
            "days": state["days"],
            "started_at": to_iso(state["started_at"]),
            "finished_at": to_iso(state["finished_at"]),
            "summary": state["summary"],
            "last_run": last_run(database),
        })

    return app


def start_scheduler(db) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=config.TIMEZONE)
    job_kwargs = {}
    if config.SCRAPE_ON_STARTUP:
        job_kwargs["next_run_time"] = now_utc() + timedelta(seconds=5)
    scheduler.add_job(
        pipeline.run_safely, "interval", minutes=config.SCRAPE_INTERVAL_MINUTES,
        kwargs={"days": config.SCRAPE_DAYS, "db": db}, id="auto_scrape",
        max_instances=1, coalesce=True, **job_kwargs,
    )
    scheduler.start()
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db = get_db()
    if not ping(db):
        raise SystemExit(f"MongoDB'ye bağlanılamadı ({config.MONGO_URI}). Servis çalışıyor mu?")
    init_indexes(db)
    log.info("Geocoding servisi: %s | Harita: %s", config.GEOCODER, config.MAP_PROVIDER)
    if config.GEOCODER == "google" and not config.GOOGLE_GEOCODING_API_KEY:
        log.warning("GEOCODER=google ama GOOGLE_GEOCODING_API_KEY tanımlı değil!")
    if config.MAP_PROVIDER == "google" and not config.GOOGLE_MAPS_JS_API_KEY:
        log.warning("MAP_PROVIDER=google ama GOOGLE_MAPS_JS_API_KEY tanımlı değil!")
    if config.MAP_PROVIDER == "osm":
        log.warning("Harita GEÇİCİ olarak OpenStreetMap ile gösteriliyor. "
                    "Proje dokümanı Google Maps istiyor; teslimden önce MAP_PROVIDER=google yapın.")
    if config.GEOCODER == "nominatim" and not config.NOMINATIM_EMAIL:
        log.warning("NOMINATIM_EMAIL tanımlı değil. Nominatim kurallarına uymak için .env'e "
                    "e-posta adresinizi yazmanız önerilir.")

    start_scheduler(db)
    app = create_app(db)
    # use_reloader=False: debug yeniden yükleyicisi zamanlayıcıyı iki kez başlatırdı.
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
