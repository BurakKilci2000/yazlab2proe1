"""
KONUM BİLGİSİ ÇIKARIMI (Proje dokümanı Bölüm 6)

Yöntem: Kural tabanlı (regex) + sözlük (gazetteer) yaklaşımı.

ADIM 1 - Metindeki TÜM konum ifadeleri bulunur:
  Seviye 5  Cadde / sokak / bulvar  "Paşa Caddesi", "Dönmez Sokak'ta"
  Seviye 4  Belirli yer (POI)       "Askeriye Sapağı", "Turka Kocaeli Stadyumu",
                                    "Hereke mevkii", "Sekapark" (bilinen yerler sözlüğü)
  Seviye 3  Mahalle / köy           "Yenişehir Mahallesi", "Fulacık ve Tahtalı mahalleleri"
  Seviye 2  Yol                     "D-100", "TEM Otoyolu", "İzmit-Kandıra yolu"
  Seviye 1  İlçe                    Kocaeli'nin 12 ilçesi
  Ad tespiti: Anahtar kelimenin ("Mahallesi", "Caddesi"...) hemen solundaki büyük
  harfle başlayan kelimeler geriye doğru toplanır (en fazla 4-5 kelime). Cümle başı
  kelimeleri ("Olay", "Kaza"), ilçe adları ve kesme işaretli kelimeler ("İzmit'in")
  addan atılır.

ADIM 2 - Haberin Kocaeli'ye ait olup olmadığı kontrol edilir:
  Yerel siteler başka illerin haberlerini de yayınlar (ör. "Bursa'da orman yangını").
  Kocaeli/ilçe anılmaları ile başka il/komşu ilçe anılmaları puanlanır; yön ifadeleri
  ("İstanbul istikametinde", "Yalova-İzmit kara yolu") sayılmaz. Başlık ve ilk cümle
  2 kat ağırlıklıdır. Dış yer puanı daha yüksekse haber kapsam dışıdır.

ADIM 3 - En spesifik konumdan genele doğru geocoding sorguları üretilir:
  "Dönmez Sokak, Paşa Caddesi, Yenişehir Mahallesi, İzmit, Kocaeli"
  "Paşa Caddesi, Yenişehir Mahallesi, İzmit, Kocaeli"
  "Yenişehir Mahallesi, İzmit, Kocaeli"
  "İzmit, Kocaeli"
  Geocoder bu listeyi sırayla dener; ilk başarılı (ve Kocaeli içinde kalan) sonuç
  kullanılır. Böylece adres net değilse "mümkün olan en spesifik konum" alınır.
  Hiç konum ifadesi yoksa haber haritada gösterilmez.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import config
from utils.text import normalize_unicode, turkish_lower

_L = "a-zçğıöşüâîû"
_U = "A-ZÇĞİÖŞÜÂÎÛ"
_SUFFIX = rf"(?:'?[{_L}]+)?"
_UPPER_TO_LOWER = {"İ": "i", "I": "ı"}

DISTRICTS = list(config.DISTRICTS)
DISTRICT_SET = set(DISTRICTS)

LEVEL_NAMES = {5: "cadde/sokak", 4: "yer", 3: "mahalle", 2: "yol", 1: "ilçe"}

STOP_WORDS = {
    "Olay", "Olayda", "Kaza", "Kazada", "Yangın", "Yangında", "Hırsızlık", "Edinilen",
    "Bilgiye", "Bilgilere", "Göre", "Dün", "Bugün", "Yarın", "Sabah", "Akşam", "Gece",
    "Öğle", "Saat", "Ayrıca", "Ancak", "Bu", "Şu", "O", "Bir", "Ekipler", "Polis",
    "İtfaiye", "Kocaeli", "Türkiye", "Haber", "Son", "Dakika", "Ve", "İle", "Da", "De",
    "İddiaya", "İlk", "Belirlemelere", "Program", "Etkinlik", "Konser", "Festival",
    # Cümle başında büyük harfle yazılan bağlaç ve zarflar (gerçek veride görüldü:
    # "Böylelikle Fuar Alanı")
    "Böylelikle", "Böylece", "Ardından", "Ayrıca", "Daha", "Hem", "Yeni", "Öte",
    "Bunun", "Şimdi", "Artık", "Ise", "İse", "Hatta", "Özellikle", "Yine",
}

# Konumu adıyla bilinen, anahtar kelime içermeyen yerler (gazetteer).
KNOWN_PLACES = [
    "Sekapark", "Seka Park", "Ormanya", "Yürüyüş Yolu", "Kartepe Kayak Merkezi",
    "Kocaeli Kongre Merkezi", "Süleyman Demirel Kültür Merkezi", "Sabancı Kültür Merkezi",
    "Kağıt Müzesi", "Kocaeli Bilim Merkezi", "İzmit Saat Kulesi", "Umuttepe",
    "Kocaeli Üniversitesi", "Gebze Teknik Üniversitesi", "UçakPark", "Kocaeli Stadyumu",
    "Darıca Hayvanat Bahçesi", "Faruk Yalçın Hayvanat Bahçesi", "Hereke", "Tavşantepe",
]

POI_TYPES = [
    "Organize Sanayi Bölgesi", "Köprülü Kavşağı", "Alışveriş Merkezi", "Kayak Merkezi",
    "Kongre Merkezi", "Kültür Merkezi", "Bilim Merkezi", "Sanat Merkezi", "Tabiat Parkı",
    "Mesire Alanı", "Sanayi Sitesi", "Spor Salonu", "Fuar Alanı", "Üst Geçidi", "Alt Geçidi",
    "Kavşağı", "Sapağı", "Köprüsü", "Meydanı", "Parkı", "Çarşısı", "Stadyumu", "Stadı",
    "Limanı", "İskelesi", "Sahili", "Plajı", "Camii", "Tüneli", "Terminali", "Otogarı",
    "Garı", "İstasyonu", "Barajı", "Gölü", "Ormanı", "Müzesi", "Salonu", "Tesisleri",
    "Fabrikası", "Kampüsü", "Yerleşkesi", "Sitesi", "OSB", "AVM",
]
# Not: "Hastanesi" bilinçli olarak YOKTUR. Haberlerde hastane, olay yerini değil
# yaralının götürüldüğü yeri belirtir ("Kocaeli Şehir Hastanesi'ne kaldırıldı").

PROVINCES = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Afyon", "Ağrı", "Aksaray", "Amasya", "Ankara",
    "Antalya", "Ardahan", "Artvin", "Aydın", "Balıkesir", "Bartın", "Batman", "Bayburt",
    "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa", "Çanakkale", "Çankırı", "Çorum",
    "Denizli", "Diyarbakır", "Düzce", "Edirne", "Elazığ", "Erzincan", "Erzurum", "Eskişehir",
    "Gaziantep", "Antep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta",
    "İstanbul", "İzmir", "Kahramanmaraş", "Maraş", "Karabük", "Karaman", "Kars", "Kastamonu",
    "Kayseri", "Kilis", "Kırıkkale", "Kırklareli", "Kırşehir", "Konya", "Kütahya", "Malatya",
    "Manisa", "Mardin", "Mersin", "Muğla", "Muş", "Nevşehir", "Niğde", "Ordu", "Osmaniye",
    "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas", "Şanlıurfa", "Urfa", "Şırnak",
    "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak", "Van", "Yalova", "Yozgat", "Zonguldak",
]
# Kocaeli'ye komşu illerin, haberlerde sık geçen ilçeleri.
NEIGHBOR_DISTRICTS = [
    "Tuzla", "Pendik", "Kartal", "Maltepe", "Kadıköy", "Üsküdar", "Ataşehir", "Ümraniye",
    "Sancaktepe", "Sultanbeyli", "Çekmeköy", "Beykoz", "Şile", "Arnavutköy", "Esenyurt",
    "Beylikdüzü", "Başakşehir", "Sapanca", "Adapazarı", "Serdivan", "Erenler", "Arifiye",
    "Akyazı", "Hendek", "Karasu", "Kocaali", "Geyve", "Pamukova", "Çiftlikköy", "Altınova",
    "Çınarcık", "Armutlu", "İznik", "Gemlik", "Orhangazi", "Mudanya", "Osmangazi",
    "Nilüfer", "Yıldırım", "İnegöl", "Kestel", "Aliağa",
]
# Soyadı/cins isim olarak da kullanılabilenler yalnızca ek ya da "ili/ilçesi" ile sayılır.
AMBIGUOUS_PLACES = {"Aydın", "Ordu", "Batman", "Van", "Muş", "Kars", "Kartal", "Yıldırım", "Rize"}

ADDRESS_WORD_RE = re.compile(
    r"^(Mahalle\w*|Mah\.|Mh\.|Cadde\w*|Cad\.|Cd\.|Soka\w*|Sok\.|Sk\.|Bulvar\w*|Blv\.|Köyü\w*)$"
)


def _first_letter_both_cases(word: str) -> str:
    first = word[0]
    lower = _UPPER_TO_LOWER.get(first, first.lower())
    return f"[{first}{lower}]{re.escape(word[1:])}" if lower != first else re.escape(word)


def _alternation(words: list[str]) -> str:
    parts = []
    for w in sorted(words, key=len, reverse=True):
        tokens = w.split()
        parts.append(r"\s+".join(_first_letter_both_cases(t) for t in tokens))
    return "|".join(parts)


MAHALLE_RE = re.compile(rf"(?<![\w])(?:[Mm]ahallesi{_SUFFIX}|Mah\.|Mh\.)")
PLURAL_MAHALLE_RE = re.compile(rf"([{_U}][{_L}]+)\s+ve\s+([{_U}][{_L}]+)\s+[Mm]ahallele")
STREET_RES = [
    ("Caddesi", re.compile(rf"(?<![\w])(?:Caddesi{_SUFFIX}|Cad\.|Cd\.)")),
    ("Sokak", re.compile(rf"(?<![\w])(?:Sokağı{_SUFFIX}|Sokak{_SUFFIX}|Sok\.|Sk\.)")),
    ("Bulvarı", re.compile(rf"(?<![\w])(?:Bulvarı{_SUFFIX}|Bulvar{_SUFFIX}|Blv\.)")),
]
_POI_BY_LENGTH = sorted(POI_TYPES, key=len, reverse=True)
_POI_TYPE_WORDS = {w for t in POI_TYPES for w in t.split()} | {"Üniversitesi", "Hastanesi", "Belediyesi"}
POI_RE = re.compile(rf"(?<![\w])(?:{_alternation(POI_TYPES)}){_SUFFIX}(?![\w])")
MEVKI_RE = re.compile(rf"(?<![\w])(?:mevki(?:i|si)?|yol ayrımı|çıkışı|gişeleri){_SUFFIX}")
KOY_RE = re.compile(rf"(?<![\w])[Kk]öyü{_SUFFIX}")
KNOWN_PLACE_RE = re.compile(rf"(?<![\w])({_alternation(KNOWN_PLACES)})(?![\w])")

ROAD_PATTERNS = [
    (re.compile(r"(?<![\w-])D\s?-?\s?(100|130)(?!\d)"), lambda m: f"D-{m.group(1)} Karayolu"),
    (re.compile(r"Kuzey Marmara Otoyolu|(?<![\w])KMO(?![\w])"), lambda m: "Kuzey Marmara Otoyolu"),
    (re.compile(r"Anadolu Otoyolu"), lambda m: "Anadolu Otoyolu"),
    (re.compile(r"(?<![\w])TEM(?![\w])"), lambda m: "TEM Otoyolu"),
    (re.compile(rf"(?<![\w-])([{_U}][{_L}]+)-([{_U}][{_L}]+)\s+(?:[Kk]ara\s?yolu|[Kk]arayolu|[Yy]olu)"),
     lambda m: f"{m.group(1)}-{m.group(2)} Yolu"),
]

# Yer adından sonra gelirse o adın "olay yeri" olmadığını gösteren ifadeler.
_NOT_A_PLACE_AFTER = re.compile(
    rf"^\s*(?:[Mm]ahalle|Körfezi|[Ii]stikamet|yön|Yön|Caddesi|Cad\.|Sokak|Sokağı|Bulvar|"
    rf"[Yy]olu|[Kk]ara ?yolu|[Oo]toyolu|[Kk]öyü|[Ss]ınır|Eğitim|Devlet|Şehir Hastanesi)"
)
_DIRECTION_AFTER = re.compile(r"^\s*(?:[Ii]stikamet|yön|Yön|[Yy]olu|[Kk]ara ?yolu|[Oo]toyolu|[Ss]ınır)")
_ILCE_AFTER = re.compile(r"^\s*ilçe", re.I)
_ADMIN_AFTER = re.compile(r"^\s*(?:ili\b|ilinde|ilçesi|ilçesinde|Valiliği|Belediyesi)")


def _place_regex(name: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(name)}('[{_L}]+)?(?![\w-])")


DISTRICT_RES = {d: _place_regex(d) for d in DISTRICTS}
KOCAELI_RE = _place_regex("Kocaeli")
FOREIGN_RES = {p: _place_regex(p) for p in dict.fromkeys(PROVINCES + NEIGHBOR_DISTRICTS)}


@dataclass
class Candidate:
    text: str
    kind: str
    level: int
    position: int

    def to_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind, "level": self.level}


@dataclass
class GeocodeQuery:
    query: str
    level: int
    label: str


@dataclass
class LocationResult:
    candidates: list[Candidate] = field(default_factory=list)
    district: str | None = None
    district_scores: dict[str, int] = field(default_factory=dict)
    queries: list[GeocodeQuery] = field(default_factory=list)
    is_local: bool = True
    local_score: int = 0
    foreign_score: int = 0
    foreign_places: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.queries)


# ------------------------------------------------------------------ yardımcılar
def _name_before(text: str, end: int, max_words: int = 4) -> str | None:
    """Anahtar kelimenin solundaki özel adı geriye doğru toplar."""
    left = text[max(0, end - 160):end]
    cut = max(left.rfind(ch) for ch in ",;:()\"\n!?")
    words = left[cut + 1:].split()

    picked: list[str] = []
    for w in reversed(words):
        if len(picked) >= max_words:
            break
        if ADDRESS_WORD_RE.match(w.split("'")[0]):
            break
        if w.endswith(".") and not re.fullmatch(r"\d+\.", w):
            break                          # cümle sonu
        if not (w[0].isupper() or w[0].isdigit()):
            break
        picked.append(w)
    picked.reverse()

    for i in range(len(picked) - 1, -1, -1):   # "İzmit'in Yenişehir" -> "Yenişehir"
        if "'" in picked[i]:
            picked = picked[i + 1:]
            break
    original = list(picked)
    while picked and (picked[0] in STOP_WORDS or picked[0] in DISTRICT_SET):
        picked.pop(0)
    if picked and picked[0] in _POI_TYPE_WORDS:
        # "Kocaeli Üniversitesi Kampüsü": baştaki "Kocaeli" atılınca ad yalnızca
        # "Üniversitesi" kalıyordu. Ad bir yer türüyle başlıyorsa orijinali korunur.
        picked = original
    if not picked and original and original[-1] not in STOP_WORDS:
        picked = [original[-1]]            # "Gölcük Mahallesi" gibi ilçe adlı mahalle
    name = " ".join(picked).strip(" .-")
    return name or None


def _lead_end(title: str, content: str) -> int:
    """Başlık + ilk cümlenin bittiği konum (ağırlıklı bölge)."""
    first = re.search(r"[.!?](\s|$)", content)
    return len(title) + 1 + (first.end() if first else min(len(content), 300))


def _count_places(text: str, lead_end: int, regexes: dict, require_admin: set[str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for name, rx in regexes.items():
        for m in rx.finditer(text):
            after = text[m.end():m.end() + 40]
            before = text[max(0, m.start() - 1):m.start()]
            if before == "-" or text[m.end():m.end() + 1] == "-":
                continue                    # "Yalova-İzmit yolu" gibi güzergâh adı
            if _NOT_A_PLACE_AFTER.match(after):
                continue
            if name in require_admin and not (m.group(1) or _ADMIN_AFTER.match(after)):
                continue
            weight = 1 + (2 if _ILCE_AFTER.match(after) or _ADMIN_AFTER.match(after) else 0)
            if m.start() < lead_end:
                weight *= 2
            scores[name] = scores.get(name, 0) + weight
    return scores


_FOREIGN_SET = set(PROVINCES) | set(NEIGHBOR_DISTRICTS)


def _belongs_to_foreign(text: str, name_start: int) -> bool:
    """'İznik'in Sarıalan Mahallesi' gibi başka bir yere ait adres mi?"""
    before = text[max(0, name_start - 40):name_start].split()
    return bool(before) and "'" in before[-1] and before[-1].split("'")[0] in _FOREIGN_SET


def _add(cands: list[Candidate], text: str | None, kind: str, level: int, pos: int) -> None:
    if not text or len(text) < 2:
        return
    if any(c.text == text and c.kind == kind for c in cands):
        return
    cands.append(Candidate(text, kind, level, pos))


# ------------------------------------------------------------------ ana fonksiyon
def extract_location(title: str, content: str) -> LocationResult:
    title = normalize_unicode(title or "")
    content = normalize_unicode(content or "")
    text = f"{title}\n{content}"
    lead_end = _lead_end(title, content)
    result = LocationResult()

    # --- ADIM 2: Kocaeli'ye mi ait? ------------------------------------------------
    district_scores = _count_places(text, lead_end, DISTRICT_RES, set())
    kocaeli_score = 0
    for m in KOCAELI_RE.finditer(text):
        after = text[m.end():m.end() + 30]
        if _DIRECTION_AFTER.match(after) or text[m.end():m.end() + 1] == "-":
            continue
        kocaeli_score += 2 if m.start() < lead_end else 1
    foreign_scores = _count_places(text, lead_end, FOREIGN_RES, AMBIGUOUS_PLACES)

    result.district_scores = district_scores
    result.local_score = kocaeli_score + sum(district_scores.values())
    result.foreign_score = sum(foreign_scores.values())
    result.foreign_places = sorted(foreign_scores, key=foreign_scores.get, reverse=True)
    result.is_local = not (result.foreign_score > result.local_score)
    if not result.is_local:
        return result

    if district_scores:
        best = max(district_scores.values())
        # eşitlikte metinde ilk geçen ilçe
        tied = [d for d, s in district_scores.items() if s == best]
        result.district = min(tied, key=lambda d: DISTRICT_RES[d].search(text).start())

    # --- ADIM 1: tüm konum ifadeleri ------------------------------------------------
    cands = result.candidates
    for m in MAHALLE_RE.finditer(text):
        name = _name_before(text, m.start())
        if name and not _belongs_to_foreign(text, text.rfind(name, 0, m.start())):
            _add(cands, f"{name} Mahallesi", "mahalle", 3, m.start())
    for m in PLURAL_MAHALLE_RE.finditer(text):
        if _belongs_to_foreign(text, m.start()):
            continue
        for g in (1, 2):
            if m.group(g) not in DISTRICT_SET:
                _add(cands, f"{m.group(g)} Mahallesi", "mahalle", 3, m.start(g))
    for kind, rx in STREET_RES:
        for m in rx.finditer(text):
            name = _name_before(text, m.start())
            if name and name not in DISTRICT_SET:
                _add(cands, f"{name} {kind}", "cadde/sokak", 5, m.start())
    for m in POI_RE.finditer(text):
        name = _name_before(text, m.start(), max_words=5)
        if name and name not in DISTRICT_SET:
            found = turkish_lower(re.sub(r"\s+", " ", m.group(0)))
            type_word = next(t for t in _POI_BY_LENGTH if found.startswith(turkish_lower(t)))
            _add(cands, f"{name} {type_word}", "yer", 4, m.start())
    for m in MEVKI_RE.finditer(text):
        name = _name_before(text, m.start(), max_words=3)
        if not name or name in DISTRICT_SET or any(name in c.text for c in cands):
            continue
        word = m.group(0)
        # "Hereke mevkii" -> "Hereke";  "İlimtepe çıkışında" -> "İlimtepe çıkışı"
        suffix = next((w for w in ("yol ayrımı", "çıkışı", "gişeleri") if word.startswith(w)), "")
        _add(cands, f"{name} {suffix}".strip(), "yer", 4, m.start())
    for m in KNOWN_PLACE_RE.finditer(text):
        if not any(m.group(1) in c.text for c in cands):
            _add(cands, m.group(1), "yer", 4, m.start())
    for m in KOY_RE.finditer(text):
        name = _name_before(text, m.start(), max_words=2)
        _add(cands, f"{name} Köyü" if name else None, "köy", 3, m.start())
    for rx, fmt in ROAD_PATTERNS:
        for m in rx.finditer(text):
            _add(cands, fmt(m), "yol", 2, m.start())
    if result.district:
        _add(cands, result.district, "ilçe", 1, DISTRICT_RES[result.district].search(text).start())

    cands.sort(key=lambda c: (-c.level, c.position))
    result.queries = build_queries(cands, result.district)
    return result


def build_queries(cands: list[Candidate], district: str | None) -> list[GeocodeQuery]:
    """En spesifikten en genele geocoding sorguları üretir."""
    ctx = ", ".join(p for p in (district, "Kocaeli") if p)
    mahalleler = [c.text for c in cands if c.kind in ("mahalle", "köy")]
    first_mahalle = mahalleler[0] if mahalleler else None
    streets = [c.text for c in cands if c.kind == "cadde/sokak"]
    sokak = [s for s in streets if s.endswith("Sokak")]
    caddeler = [s for s in streets if not s.endswith("Sokak")]

    queries: list[GeocodeQuery] = []

    def add(parts: list[str | None], level: int, label: str) -> None:
        q = ", ".join(p for p in parts + [ctx] if p)
        if not any(x.query == q for x in queries):
            queries.append(GeocodeQuery(q, level, label))

    if streets:
        main = (sokak[:1] + caddeler[:1]) or streets[:1]
        add(main + [first_mahalle], 5, " / ".join(main))
        for s in caddeler[:1] + sokak[:1]:
            add([s, first_mahalle], 5, s)
    for c in cands:
        if c.kind == "yer":
            add([c.text], 4, c.text)
    for m in mahalleler[:3]:
        add([m], 3, m)
    for c in cands:
        if c.kind == "yol":
            add([c.text], 2, c.text)
    if district:
        add([], 1, district)
    return queries
