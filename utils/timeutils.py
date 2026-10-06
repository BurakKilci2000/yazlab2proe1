"""
Tarih/saat yardımcıları.

Kural: Veritabanına her zaman UTC kaydedilir. Haber sitelerinden gelen
saat bilgisi saat dilimi içermiyorsa Türkiye saati (Europe/Istanbul)
kabul edilir. Arayüzde tarihler tekrar Türkiye saatine çevrilerek gösterilir.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import config

LOCAL_TZ = ZoneInfo(config.TIMEZONE)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def days_ago_utc(days: int) -> datetime:
    return now_utc() - timedelta(days=days)


def localize_scraped(dt: datetime | None) -> datetime | None:
    """Siteden okunan tarih: saat dilimi yoksa Türkiye saati varsayılır, UTC'ye çevrilir."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """Veritabanından okunan tarih: saat dilimi yoksa zaten UTC'dir."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    dt = as_utc(dt)
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def parse_local_date(value: str | None) -> date | None:
    """'2026-04-01' biçimindeki tarih kutusu değerini okur."""
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def local_day_range_to_utc(start: date | None, end: date | None):
    """
    Arayüzden gelen gün aralığını UTC aralığına çevirir.
    [start 00:00 TR, end+1 00:00 TR) şeklinde, bitiş günü dahil.
    """
    start_dt = (
        datetime.combine(start, time.min, LOCAL_TZ).astimezone(timezone.utc) if start else None
    )
    end_dt = (
        datetime.combine(end + timedelta(days=1), time.min, LOCAL_TZ).astimezone(timezone.utc)
        if end else None
    )
    return start_dt, end_dt
