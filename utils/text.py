"""
Türkçe'ye özgü metin yardımcıları.

Neden gerekli? Python'un str.lower() fonksiyonu Türkçe kurallarını bilmez:
    "İZMİT".lower()  -> "i̇zmi̇t"  (i + birleşik nokta karakteri, yanlış)
    "IŞIK".lower()   -> "işik"     (ı olmalıydı, yanlış)
Bu yüzden büyük/küçük harf dönüşümünü kendimiz yapıyoruz.
"""
from __future__ import annotations

import re
import unicodedata

_QUOTE_MAP = str.maketrans({
    "\u2019": "'", "\u2018": "'", "\u02bc": "'", "`": "'", "\u00b4": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",
})
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_CIRCUMFLEX = str.maketrans({"â": "a", "î": "i", "û": "u", "Â": "A", "Î": "İ", "Û": "U"})


def normalize_unicode(text: str) -> str:
    """Unicode biçimini birleştirir, tırnak/kesme/tire çeşitlerini tek tipe indirir."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_QUOTE_MAP)
    return _ZERO_WIDTH_RE.sub("", text)


def turkish_lower(text: str) -> str:
    """Türkçe kurallarına uygun küçük harfe çevirme."""
    if not text:
        return ""
    return text.replace("I", "ı").replace("İ", "i").lower()


def remove_circumflex(text: str) -> str:
    """'hâkimiyet' -> 'hakimiyet' gibi şapkalı harfleri sadeleştirir."""
    return text.translate(_CIRCUMFLEX)


def normalize_for_matching(text: str) -> str:
    """
    Anahtar kelime eşleştirmesi için metni standart hale getirir:
    küçük harf, şapkasız, noktalama yerine boşluk, tek boşluk.
    "Direksiyon HÂKİMİYETİNİ kaybetti!" -> "direksiyon hakimiyetini kaybetti"
    """
    text = remove_circumflex(turkish_lower(normalize_unicode(text)))
    text = text.replace("'", "")
    text = re.sub(r"[^0-9a-zçğıöşü]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ASCII_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def ascii_fold(text: str) -> str:
    """Karşılaştırma için Türkçe harfleri sadeleştirir: 'İzmit' == 'Izmit' == 'izmit'."""
    return turkish_lower(normalize_unicode(text or "")).translate(_ASCII_FOLD).strip()
