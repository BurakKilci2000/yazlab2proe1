"""
Haber sayfalarındaki yayın tarihini okuma.

Desteklenen biçimler:
  ISO 8601          : 2026-09-22T16:18:00+03:00   (JSON-LD, meta etiketleri)
  RSS (RFC 822)     : Tue, 22 Sep 2026 16:18:00 +0300
  Türkçe metin      : 22 Eylül 2026 Salı 16:18  /  22 Eyl 2026 - 16:18
  Sayısal           : 22.09.2026 16:18
Dönen değer her zaman UTC'dir (bkz. utils.timeutils.localize_scraped).
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from dateutil import parser as dateparser

from utils.text import turkish_lower
from utils.timeutils import localize_scraped

_MONTHS = {
    "oca": 1, "şub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6,
    "tem": 7, "ağu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
}
_TR_DATE_RE = re.compile(
    r"(\d{1,2})\s+(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık|"
    r"Oca|Şub|Mar|Nis|May|Haz|Tem|Ağu|Eyl|Eki|Kas|Ara)\.?\s+(\d{4})"
    r"(?:\D{0,25}?(\d{1,2})[:.](\d{2}))?"
)
_NUM_DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})(?:\D{1,5}(\d{1,2})[:.](\d{2}))?")


def parse_iso(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return localize_scraped(dateparser.isoparse(value.strip()))
    except (ValueError, OverflowError):
        return None


def parse_rfc822(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return localize_scraped(parsedate_to_datetime(value.strip()))
    except (TypeError, ValueError, IndexError):
        return None


def parse_turkish_date(text: str) -> datetime | None:
    if not text:
        return None
    m = _TR_DATE_RE.search(text)
    if m:
        day, month_name, year, hh, mm = m.groups()
        month = _MONTHS.get(turkish_lower(month_name)[:3])
        try:
            return localize_scraped(datetime(int(year), month, int(day), int(hh or 0), int(mm or 0)))
        except (TypeError, ValueError):
            pass
    m = _NUM_DATE_RE.search(text)
    if m:
        day, month, year, hh, mm = m.groups()
        try:
            return localize_scraped(datetime(int(year), int(month), int(day), int(hh or 0), int(mm or 0)))
        except ValueError:
            pass
    return None


def parse_any(value) -> datetime | None:
    """Biçimi bilinmeyen bir tarih metnini sırayla dener."""
    return parse_iso(value) or parse_rfc822(value) or parse_turkish_date(value or "")
