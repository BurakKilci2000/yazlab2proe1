"""
VERİ TEMİZLEME VE ÖN İŞLEME (Proje dokümanı Bölüm 4)

Zorunlu adımların her biri ayrı fonksiyondur:
  1. HTML tag temizliği              -> html_to_lines()
  2. Reklam / alakasız bölüm temizliği -> _remove_noise_elements(), _is_noise_line()
  3. Metin normalizasyonu            -> utils.text.normalize_unicode()
  4. Gereksiz özel karakter temizliği -> remove_special_characters()
  5. Fazla boşluk temizliği          -> normalize_whitespace()
Analiz için ayrıca küçük harfli/noktalamasız sürüm üretilir
(utils.text.normalize_for_matching).
"""
from __future__ import annotations

import html as html_lib
import re

from bs4 import BeautifulSoup, Comment

from utils.text import normalize_unicode, turkish_lower

# Haber metni içermeyen etiketler tamamen silinir.
REMOVE_TAGS = (
    "script", "style", "noscript", "iframe", "form", "button", "svg", "nav",
    "footer", "header", "aside", "figure", "figcaption", "video", "audio",
    "ins", "object", "embed", "select", "input", "picture", "img",
)
# class/id değerinde bu kelimeler geçen bloklar reklam veya alakasız içeriktir.
NOISE_ATTR_RE = re.compile(
    r"(reklam|advert|\bads?\b|[-_]ads?[-_]|^ads?[-_]|banner|sponsor|related|ilgili|benzer|"
    r"diger-?haber|paylas|share|social|sosyal|comment|yorum|etiket|\btags?\b|newsletter|"
    r"abone|breadcrumb|author|yazar|recommend|outbrain|taboola|popular|populer|"
    r"most-?read|cok-?okunan|son-?dakika-?bant|google-?news|whatsapp)",
    re.I,
)
# Satır bazında tanınan gürültü kalıpları (küçük harfli metinde aranır).
NOISE_LINE_RE = re.compile(
    r"(^abone ol|google news|^ilgili haber|haberin devamı|devamı için|tıklayın|tıkla$|"
    r"tüm haberleri$|haber albümü|^yazdır$|reklam|sponsorlu|bizi takip|whatsapp kanal|"
    r"^kaynak\s*:|^foto(ğraf)?\s*:|^editör\s*:|^#|yorum yaz|topluluk kuralları|"
    r"çerez|cookie|^son dakika$|^paylaş|^\d{1,2}:\d{2}\s|"
    r"^\d{1,2}[ ./]\S+[ ./]\d{4}(\s*-?\s*\d{1,2}[:.]\d{2})?$)"
)
AGENCY_LINES = {
    "ihlas haber ajansı", "anadolu ajansı", "demirören haber ajansı", "haber merkezi",
    "aa", "iha", "dha", "anka", "anka haber ajansı",
}
_ALLOWED_CHARS_RE = re.compile(r"[^\w\s.,;:!?'\"()\-/%&+₺]")
_REPEATED_PUNCT_RE = re.compile(r"([!?.,;:])\1{2,}")


def _remove_noise_elements(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()

    total_p = sum(len(p.get_text(" ", strip=True)) for p in soup.find_all("p")) or 1
    for el in list(soup.find_all(True)):
        if getattr(el, "decomposed", False) or el.parent is None:
            continue  # üst bloğu ile birlikte zaten silinmiş
        attrs = " ".join(el.get("class", []) or []) + " " + (el.get("id") or "")
        if not attrs.strip() or not NOISE_ATTR_RE.search(attrs):
            continue
        # Ana haber kapsayıcısını yanlışlıkla silmemek için: paragraf metninin
        # büyük kısmını içeren blok gürültü sayılmaz.
        own_p = sum(len(p.get_text(" ", strip=True)) for p in el.find_all("p"))
        if own_p / total_p < 0.6:
            el.decompose()


def html_to_lines(html: str) -> list[str]:
    """HTML'den etiketleri temizleyip paragraf satırlarını döndürür."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    _remove_noise_elements(soup)
    for br in soup.find_all("br"):
        br.replace_with("\n")

    blocks = soup.find_all(["p", "h2", "h3", "h4", "li", "blockquote"])
    if blocks:
        lines = []
        for b in blocks:
            if b.find_parent(["p", "li", "blockquote"]) is not None:
                continue  # iç içe etiketlerde metni iki kez almamak için
            lines.extend(b.get_text(" ", strip=False).split("\n"))
    else:
        lines = soup.get_text("\n").split("\n")
    return lines


def remove_special_characters(text: str) -> str:
    """Harf, rakam, boşluk ve temel noktalama dışındaki karakterleri (emoji vb.) siler."""
    text = _ALLOWED_CHARS_RE.sub(" ", text).replace("_", " ")
    return _REPEATED_PUNCT_RE.sub(r"\1", text)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


_EDGE_CHARS = " .:-!?"


def _is_noise_line(line: str, title_key: str) -> bool:
    low = turkish_lower(line).strip(_EDGE_CHARS)
    if not low:
        return True
    if low in AGENCY_LINES:
        return True
    if title_key and low == title_key:
        return True            # görsel altında tekrarlanan başlık
    if NOISE_LINE_RE.search(low):
        return True
    if len(low.split()) < 3:
        return True            # tek başına kalan kısa ara başlıklar / etiketler
    return False


def clean_lines(lines: list[str], title: str | None = None) -> str:
    title_key = turkish_lower(normalize_unicode(title or "")).strip(_EDGE_CHARS)
    seen: set[str] = set()
    result: list[str] = []
    for raw in lines:
        line = normalize_whitespace(remove_special_characters(normalize_unicode(raw)))
        if _is_noise_line(line, title_key):
            continue
        key = turkish_lower(line)
        if key in seen:
            continue           # tekrar eden satırlar
        seen.add(key)
        result.append(line)
    return "\n".join(result)


def clean_html(html: str, title: str | None = None) -> str:
    return clean_lines(html_to_lines(html), title)


def clean_text(text: str, title: str | None = None) -> str:
    """Düz metin (JSON-LD articleBody gibi) için temizlik."""
    if not text:
        return ""
    text = html_lib.unescape(text)
    if "<" in text and ">" in text:          # metin içinde HTML kalmışsa
        return clean_html(text, title)
    return clean_lines(re.split(r"\n+|(?<=[.!?])\s{2,}", text), title)


def build_article_text(title: str, body_html: str, ld_body: str, description: str) -> str:
    """
    Haberin nihai temiz metnini oluşturur.
    JSON-LD articleBody reklam içermediği için yeterince uzunsa tercih edilir;
    değilse HTML gövdesi kullanılır. Haber özeti (spot) metinde yoksa başa eklenir,
    çünkü konum bilgisi çoğu zaman spotta geçer.
    """
    from_ld = clean_text(ld_body, title)
    from_html = clean_html(body_html, title)
    content = from_ld if len(from_ld) >= 150 else max(from_html, from_ld, key=len)

    spot = clean_text(description, title)
    if spot and turkish_lower(spot)[:60] not in turkish_lower(content):
        content = f"{spot}\n{content}" if content else spot
    return content.strip()
