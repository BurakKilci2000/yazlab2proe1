"""
HABER TÜRÜ SINIFLANDIRMA (Proje dokümanı Bölüm 5)

Yöntem: Ağırlıklı anahtar kelime puanlaması.

1. Başlık ve içerik normalize edilir (küçük harf, şapkasız, noktalamasız).
2. Her tür için anahtar kelimeler aranır. Her kelimenin bir ağırlığı vardır:
     5-4 : Türü neredeyse kesin gösteren ifade ("trafik kaza", "hırsız")
     3-2 : Güçlü ipucu ("çarpıştı", "alev aldı")
     1   : Zayıf ipucu, tek başına yetmez ("sürücü", "itfaiye")
    <0   : Negatif kelime, yanlış eşleşmeyi bastırır ("iş kazası", "su kesintisi")
3. Kelime sonuna "$" konursa yalnızca tam kelime eşleşir ("kaza$" -> "kaza" evet,
   "kazanç" hayır). "$" yoksa kelime kökü olarak eşleşir; Türkçe ekler kabul edilir
   ("yangın" -> "yangında", "yangını").
4. Başlıktaki eşleşmeler 2 kat sayılır. Aynı kelime en fazla 3 kez puanlanır.
5. GÜÇLÜ KELİME ŞARTI: Bir türün seçilebilmesi için o türün en az bir güçlü
   kelimesi (ağırlık >= ANCHOR_WEIGHT) haberde geçmelidir. "şüpheli", "yakalandı",
   "sürücü" gibi zayıf kelimeler yalnızca destekleyicidir; tek başlarına bir haberi
   o türe sokamazlar. (Gerçek verilerle yapılan testte, cinayet ve uyuşturucu
   haberlerinin yalnızca zayıf kelimelerle "Hırsızlık" puanı topladığı görüldü.)
   Ayrıca puanı MIN_SCORE altındaki türler elenir. Hiçbir tür kalmazsa haber bu
   5 türden biri değildir ve kaydedilmez.
6. Birden fazla tür aday ise (puanı en yüksek puanın %60'ına ulaşan türler),
   PRIORITY listesindeki sıraya göre seçim yapılır.

Öncelik sırası gerekçesi:
  Yangın > Trafik Kazası > Hırsızlık > Elektrik Kesintisi > Kültürel Etkinlikler
  Can ve mal güvenliğini en doğrudan tehdit eden ve acil müdahale gerektiren olay
  önce gelir. Örn. "kaza sonrası araç alev aldı" haberinde iki tür de güçlüyse
  yangın seçilir; "trafo yangını nedeniyle elektrik kesildi" haberinde de yangın
  seçilir. Kültürel etkinlik bir acil durum olmadığı için en sondadır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from utils.text import normalize_for_matching

CATEGORIES = ["Trafik Kazası", "Yangın", "Elektrik Kesintisi", "Hırsızlık", "Kültürel Etkinlikler"]
PRIORITY = ["Yangın", "Trafik Kazası", "Hırsızlık", "Elektrik Kesintisi", "Kültürel Etkinlikler"]
MIN_SCORE = 4
ANCHOR_WEIGHT = 3
CLOSE_RATIO = 0.6
TITLE_WEIGHT = 2
MAX_HITS_PER_KEYWORD = 3

KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "Trafik Kazası": [
        ("trafik kaza", 5), ("zincirleme kaza", 5), ("zincirleme", 2), ("kafa kafaya", 3),
        ("yayaya çarp", 4), ("takla at", 3), ("şarampol", 3), ("kontrolden çık", 3),
        ("direksiyon hakimiyet", 3), ("çarpıştı", 3), ("çarpışma", 3), ("çarpışan", 3),
        ("arkadan çarp", 3), ("bariyer", 2), ("refüj", 2), ("devrildi", 3), ("devrilen", 3), ("sürücüsü yaralandı", 3),
        ("maddi hasar", 3), ("kaza$", 3), ("kazada$", 3), ("kazaya$", 3), ("kazayı$", 3),
        ("kazayla$", 3), ("kazası$", 2), ("kazalar", 2), ("kazazede", 3),
        ("otomobil", 1), ("motosiklet", 1), ("kamyon", 1), ("tır$", 1), ("tırın$", 1),
        ("minibüs", 1), ("sürücü", 1), ("yaralandı", 1), ("ambulans", 1),
        ("trafik ekip", 1), ("plakalı", 1),
        ("iş kaza", -6), ("ağaç devril", -6), ("direk devril", -6),
        ("yeni kavşak", -5), ("kavşak düzenleme", -5),
        ("kavşak çalışma", -5), ("yol çalışma", -4), ("asfalt", -3), ("ihale", -3),
    ],
    "Yangın": [
        ("yangın", 4), ("alevlere teslim", 3), ("alev aldı", 3), ("alev alev", 3), ("alev", 1),
        ("küle dön", 4), ("kül oldu", 4), ("kundak", 4), ("tutuştu", 3), ("tutuşma", 2),
        ("söndürül", 3), ("söndürme", 2), ("itfaiye", 1), ("dumandan etkilen", 3),
        ("yanarak", 2), ("yandı$", 3), ("patlama", 1),
        ("tatbikat", -5), ("yangın söndürme tüpü", -2),
    ],
    "Elektrik Kesintisi": [
        ("elektrik kesinti", 5), ("elektrikler kesil", 5), ("elektrikler gitti", 4),
        ("elektriksiz", 4), ("enerji kesinti", 5), ("planlı kesinti", 4), ("plansız kesinti", 4),
        ("kesinti yapılacak", 3), ("kesinti uygulanacak", 3), ("elektrik verilemeye", 5),
        ("elektrik verilmeye", 5), ("sedaş", 2), ("elektrik arıza", 4),
        ("karanlıkta kal", 2), ("trafo", 1), ("elektrik", 1), ("kesinti", 1),
        ("su kesinti", -5), ("doğalgaz kesinti", -5), ("doğal gaz kesinti", -5),
        ("sanayi odası", -5), ("seçim", -3), ("meclis üye", -3),
    ],
    "Hırsızlık": [
        ("hırsız", 5), ("çaldı$", 3), ("çaldılar", 3), ("çalındı", 3), ("çalınan", 3),
        ("çalıntı", 4), ("çalarak", 3), ("çaldığı", 3), ("çaldıkları", 3), ("gasp", 4),
        ("soygun", 4), ("soyuldu", 4), ("yankesici", 4), ("kapkaç", 4),
        ("ziynet", 1), ("ele geçirildi", 1), ("şüpheli", 1), ("gözaltına", 1),
        ("yakalandı", 1), ("tutuklandı", 1),
        ("öldür", -5), ("cinayet", -5), ("uyuşturucu", -3), ("usulsüzlük", -4),
        ("rüşvet", -4), ("dolandırıcılık", -3),
        ("istiklal marşı", -5), ("kapı çal", -4), ("kapısını çal", -4), ("zil çal", -4),
    ],
    "Kültürel Etkinlikler": [
        # "konser" kökü "konserve"yi, "sergi" kökü "sergiledi"yi, "opera" kökü
        # "operasyon"u da yakalıyordu; bu kelimeler yalnızca belirli biçimleriyle eşleşir.
        ("konser$", 4), ("konseri", 4), ("konserde", 4), ("konsere", 4), ("konserler", 4),
        ("konserden", 4), ("tiyatro", 4),
        ("sergi$", 3), ("sergisi", 3), ("sergide$", 3), ("sergiye$", 3), ("sergiler", 3), ("festival", 4), ("söyleşi", 3),
        ("dinleti", 4), ("müzikal", 3), ("opera$", 3), ("operası", 3), ("operada$", 3), ("bale$", 3), ("resital", 4),
        ("orkestra", 3), ("koro$", 2), ("korosu", 3), ("kültür sanat", 3), ("kültürel", 2),
        ("etkinlik", 2), ("sahne", 2), ("gösterim", 2), ("gösteri", 1), ("sinema", 2),
        ("şiir", 2), ("imza günü", 3), ("kitap fuar", 4), ("fuar", 1), ("şenlik", 3),
        ("panayır", 3), ("sanatçı", 2), ("sanatsever", 3), ("müze", 2), ("atölye", 1),
        ("konferans", 1), ("kültür merkezi", 2), ("kültür ve sanat", 3),
        ("sempozyum", 3), ("resim yarışması", 3), ("film gösterim", 3),
        ("sanat etkinli", 3), ("kitap okuma", 2),
        ("uyuşturucu", -6), ("operasyon", -4), ("tutuklan", -4), ("gözaltı", -4),
        ("futbol", -4), ("transfer", -3), ("maç$", -4), ("maçı", -4), ("lig$", -3),
        ("aday", -3), ("seçim", -3), ("atama", -3), ("atandı", -3),
    ],
}


@dataclass
class ClassificationResult:
    category: str | None
    scores: dict[str, int] = field(default_factory=dict)
    matched: dict[str, list[str]] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"scores": self.scores, "matched_keywords": self.matched, "candidates": self.candidates}


def _compile(keyword: str) -> re.Pattern:
    exact = keyword.endswith("$")
    norm = normalize_for_matching(keyword.rstrip("$"))
    body = r"\s+".join(re.escape(part) for part in norm.split())
    tail = r"(?![0-9a-zçğıöşü])" if exact else ""
    return re.compile(rf"(?<![0-9a-zçğıöşü]){body}{tail}")


# Desenler bir kez derlenir (her haber için tekrar derlemek yavaş olurdu).
_COMPILED = {
    cat: [(kw, weight, _compile(kw)) for kw, weight in items]
    for cat, items in KEYWORDS.items()
}


def _score(text: str, multiplier: int, scores: dict, matched: dict, anchored: set) -> None:
    for cat, patterns in _COMPILED.items():
        for kw, weight, pattern in patterns:
            hits = min(len(pattern.findall(text)), MAX_HITS_PER_KEYWORD)
            if hits:
                scores[cat] += weight * hits * multiplier
                if weight >= ANCHOR_WEIGHT:
                    anchored.add(cat)
                label = kw.rstrip("$")
                if label not in matched[cat]:
                    matched[cat].append(label)


def classify(title: str, content: str) -> ClassificationResult:
    scores = {cat: 0 for cat in CATEGORIES}
    matched: dict[str, list[str]] = {cat: [] for cat in CATEGORIES}
    anchored: set[str] = set()      # en az bir güçlü kelimesi geçen türler
    _score(normalize_for_matching(title), TITLE_WEIGHT, scores, matched, anchored)
    _score(normalize_for_matching(content), 1, scores, matched, anchored)

    eligible = {c: s for c, s in scores.items() if c in anchored and s >= MIN_SCORE}
    if not eligible:
        return ClassificationResult(None, scores, {k: v for k, v in matched.items() if v})

    top = max(eligible.values())
    candidates = [c for c in CATEGORIES if c in eligible and eligible[c] >= top * CLOSE_RATIO]
    chosen = next(c for c in PRIORITY if c in candidates)
    return ClassificationResult(chosen, scores, {k: v for k, v in matched.items() if v}, candidates)
