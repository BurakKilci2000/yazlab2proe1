"""
Kayıtlı haberleri GÜNCEL sınıflandırma kurallarıyla yeniden değerlendirir.

Anahtar kelimeler değiştirildiğinde, siteleri yeniden taramaya gerek kalmadan
veritabanındaki haber metinleri (news.content) üzerinden tekrar sınıflandırma
yapılır. Her haber için puanlar ve eşleşen kelimeler gösterilir; bu çıktı hem
kelime listesinin ince ayarında hem de sunumda "bu haber neden bu türde?"
sorusunu cevaplamakta kullanılır.

Kullanım (proje klasöründe):
    python -m tools.reclassify               # sadece rapor, hiçbir şey değişmez
    python -m tools.reclassify --all         # değişmeyenleri de listele
    python -m tools.reclassify --apply       # değişiklikleri veritabanına uygula

--apply ile:
  - Türü değişen haberin `type` ve `classification` alanları güncellenir.
  - Artık hiçbir türe girmeyen haber `news` koleksiyonundan silinir; tüm kaynak
    linkleri `processed_urls` içinde "no_category" olarak işaretlenir. Böylece
    sonraki taramalarda bu linkler tekrar işlenmez.
"""
from __future__ import annotations

import argparse
from collections import Counter

from db.mongo import get_db
from processing.classifier import classify
from utils.timeutils import now_utc


def evaluate(db) -> list[dict]:
    rows = []
    for doc in db.news.find({}, {"title": 1, "content": 1, "type": 1, "sources": 1}):
        result = classify(doc.get("title", ""), doc.get("content", ""))
        rows.append({"doc": doc, "old": doc.get("type"), "new": result.category, "result": result})
    return rows


def apply_changes(db, rows: list[dict]) -> Counter:
    stats = Counter()
    for row in rows:
        doc, old, new, result = row["doc"], row["old"], row["new"], row["result"]
        if new == old:
            continue
        if new is None:
            db.news.delete_one({"_id": doc["_id"]})
            for src in doc.get("sources", []):
                db.processed_urls.update_one(
                    {"url": src["url"]},
                    {"$set": {"url": src["url"], "status": "no_category", "title": doc.get("title"),
                              "site_name": src.get("site_name"), "reason": "yeniden sınıflandırma",
                              "classification": result.to_dict(), "updated_at": now_utc()}},
                    upsert=True,
                )
            stats["silindi"] += 1
        else:
            db.news.update_one(
                {"_id": doc["_id"]},
                {"$set": {"type": new, "classification": result.to_dict(), "updated_at": now_utc()}},
            )
            stats["türü değişti"] += 1
    return stats


def show(rows: list[dict], show_all: bool) -> None:
    changed = [r for r in rows if r["new"] != r["old"]]
    for row in (rows if show_all else changed):
        doc, result = row["doc"], row["result"]
        mark = "  " if row["new"] == row["old"] else "≠ "
        print(f"\n{mark}{doc['title']}")
        print(f"   Eski tür : {row['old']}")
        print(f"   Yeni tür : {row['new'] or '— (hiçbir türe girmiyor)'}")
        scores = {k: v for k, v in result.scores.items() if v}
        if scores:
            print(f"   Puanlar  : {scores}")
        for cat, words in result.matched.items():
            print(f"   {cat}: {', '.join(words)}")
    print(f"\nToplam {len(rows)} haber, {len(changed)} tanesinin sonucu değişiyor.")
    print("Dağılım:", dict(Counter(r["new"] or "— silinecek" for r in rows)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="değişiklikleri veritabanına uygula")
    parser.add_argument("--all", action="store_true", help="değişmeyen haberleri de göster")
    args = parser.parse_args()

    db = get_db()
    rows = evaluate(db)
    show(rows, args.all)
    if args.apply:
        stats = apply_changes(db, rows)
        print("\nUygulandı:", dict(stats) or "değişiklik yok")
    else:
        print("\nBu bir önizlemedir; veritabanı değişmedi. Uygulamak için: "
              "python -m tools.reclassify --apply")


if __name__ == "__main__":
    main()
