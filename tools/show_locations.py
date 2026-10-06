"""
Sunum yardımcısı: Veritabanındaki haberlerin tespit edilen konumlarını ve
atlanan haberlerin nedenlerini terminalde gösterir.

Kullanım (proje klasöründe):
    python -m tools.show_locations              # son 10 haber
    python -m tools.show_locations --limit 30
    python -m tools.show_locations --skipped    # atlanan linkler ve nedenleri
"""
from __future__ import annotations

import argparse
from collections import Counter

from db.mongo import get_db
from utils.timeutils import LOCAL_TZ, as_utc

REASONS = {
    "saved": "kaydedildi", "merged": "başka kaynaktaki aynı haberle birleştirildi",
    "no_category": "5 haber türünden hiçbirine girmiyor", "not_local": "Kocaeli dışı olay",
    "no_location": "konum bulunamadı", "geocode_failed": "konum koordinata çevrilemedi",
    "geocode_error": "geocoding servisine ulaşılamadı (tekrar denenecek)",
    "out_of_range": "tarih aralığı dışında", "no_date": "yayın tarihi okunamadı",
    "fetch_failed": "sayfa indirilemedi", "parse_failed": "sayfa ayrıştırılamadı",
}


def fmt(dt) -> str:
    dt = as_utc(dt)
    return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M") if dt else "-"


def show_news(db, limit: int) -> None:
    for doc in db.news.find({}, {"embedding": 0, "content": 0}).sort("published_at", -1).limit(limit):
        loc = doc.get("location", {})
        print(f"\n[{doc['type']}] {doc['title']}")
        print(f"  Tarih    : {fmt(doc['published_at'])}")
        print(f"  Kaynaklar: {', '.join(s['site_name'] for s in doc['sources'])}")
        print(f"  Adaylar  : {', '.join(c['text'] + ' (' + c['kind'] + ')' for c in loc.get('candidates', []))}")
        print(f"  Seçilen  : {doc['location_text']}  [{loc.get('level_name')}]")
        print(f"  Servis   : {loc.get('geocoder', 'google')}")
        print(f"  Adres    : {loc.get('formatted_address')}  ->  {doc['lat']:.5f}, {doc['lng']:.5f}")
        for a in loc.get("attempts", []):
            print(f"     {'✓' if a['ok'] else '✗'} {a['query']}  ({a['reason']})")


def show_skipped(db, limit: int) -> None:
    counts = Counter(d["status"] for d in db.processed_urls.find({}, {"status": 1}))
    print("Link durumları:")
    for status, n in counts.most_common():
        print(f"  {n:5d}  {status:15s} {REASONS.get(status, '')}")
    print()
    query = {"status": {"$nin": ["saved", "merged"]}}
    for doc in db.processed_urls.find(query).sort("updated_at", -1).limit(limit):
        print(f"- [{doc['status']}] {doc.get('title') or doc['url']}")
        if doc.get("foreign_places"):
            print(f"    dış yerler: {', '.join(doc['foreign_places'])}")
        if doc.get("reason"):
            print(f"    neden: {doc['reason']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--skipped", action="store_true")
    args = parser.parse_args()
    db = get_db()
    if args.skipped:
        show_skipped(db, args.limit)
    else:
        show_news(db, args.limit)


if __name__ == "__main__":
    main()
