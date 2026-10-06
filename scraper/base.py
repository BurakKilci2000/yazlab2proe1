"""
Tüm haber sitesi scraper'larının ortak temel sınıfı.

Bir sitenin taranması iki aşamadan oluşur:

1) KEŞİF (discover): Haber linklerini bulmak.
   a) RSS beslemeleri   -> link + yayın tarihi birlikte gelir (en verimli yol)
   b) Site haritası      -> link + tarih
   c) Liste sayfaları    -> ana sayfa, kategori ve etiket sayfalarındaki <a> linkleri
   Bulunan linkler sitenin haber URL kalıbına (regex) uymak zorundadır; böylece
   menü, yazar, reklam linkleri elenir.

2) DETAY (parse_article): Her haber sayfasından başlık, tarih ve gövde alınır.
   Öncelik sırası:
   - JSON-LD (<script type="application/ld+json">, NewsArticle şeması)
     Haber siteleri bunu Google için yayınlar; başlık/tarih/metin temiz gelir.
   - Open Graph / meta etiketleri (og:title, article:published_time)
   - HTML gövdesi (siteye özel CSS seçicileri, yoksa "en çok paragraf içeren blok")

Son 3 gün kuralı: Haber ID'leri bu sitelerde artan sayılardır. Linkler yeniden
eskiye sıralanır; arka arkaya belirli sayıda eski habere rastlanınca o sitenin
taraması durdurulur (gereksiz istek atılmaz).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

import config
from scraper.dates import parse_any, parse_iso, parse_rfc822, parse_turkish_date
from scraper.http_client import HttpClient

log = logging.getLogger(__name__)

NEWS_LD_TYPES = {"NewsArticle", "Article", "ReportageNewsArticle", "BlogPosting", "WebPage"}


@dataclass
class RawArticle:
    """Siteden okunan ham haber (henüz temizlenmemiş)."""
    url: str
    site_name: str
    title: str
    published_at: datetime | None
    body_html: str = ""        # haber gövdesinin HTML'i
    ld_body: str = ""          # JSON-LD articleBody (varsa)
    description: str = ""      # haber özeti / spot
    discovered_url: str = ""   # listede bulunan link (canonical'dan farklıysa)


@dataclass
class ScrapeItem:
    """Bir linkin tarama sonucu: ya haber ya da hata."""
    url: str
    site_name: str
    article: RawArticle | None = None
    error_status: str | None = None   # fetch_failed / parse_failed / no_date
    error: str | None = None


@dataclass
class LinkInfo:
    url: str
    date_hint: datetime | None = None
    article_id: int = 0


@dataclass
class SiteReport:
    site_name: str
    links_found: int = 0
    fetched: int = 0
    skipped_known: int = 0
    skipped_old_by_hint: int = 0
    errors: list[str] = field(default_factory=list)


class BaseScraper:
    site_name: str = ""
    base_url: str = ""
    feed_paths: tuple[str, ...] = ()
    sitemap_paths: tuple[str, ...] = ("/sitemap.xml",)
    listing_paths: tuple[str, ...] = ("/",)
    article_path_regex: re.Pattern = re.compile(r"^$")
    content_selectors: tuple[str, ...] = ()

    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient()
        parsed = urlparse(self.base_url)
        self._host = parsed.netloc.lower()
        self._bare_host = self._host.removeprefix("www.")
        self.report = SiteReport(self.site_name)

    # ------------------------------------------------------------------ URL
    def normalize_url(self, href: str | None) -> str | None:
        """Linki mutlak, sorgu parametresiz ve tek biçimli hale getirir."""
        if not href:
            return None
        href = href.strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            return None
        parsed = urlparse(urljoin(self.base_url + "/", href))
        if parsed.scheme not in ("http", "https"):
            return None
        if parsed.netloc.lower().removeprefix("www.") != self._bare_host:
            return None
        path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
        return urlunparse(("https", self._host, path, "", "", ""))

    def is_article_url(self, url: str) -> bool:
        return bool(self.article_path_regex.search(urlparse(url).path))

    def article_id(self, url: str) -> int:
        m = self.article_path_regex.search(urlparse(url).path)
        if m and m.groups():
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                pass
        m = re.search(r"(\d{4,})", urlparse(url).path)
        return int(m.group(1)) if m else 0

    # ----------------------------------------------------------- KEŞİF
    def _add_link(self, found: dict[int, LinkInfo], url: str | None, date_hint=None) -> None:
        url = self.normalize_url(url)
        if not url or not self.is_article_url(url):
            return
        aid = self.article_id(url)
        key = aid or hash(url)
        current = found.get(key)
        if current is None:
            found[key] = LinkInfo(url=url, date_hint=date_hint, article_id=aid)
        else:
            # Aynı haberin farklı yolları olabilir; en kısa olanı tutulur.
            if len(url) < len(current.url):
                current.url = url
            if date_hint and not current.date_hint:
                current.date_hint = date_hint

    def _parse_feed(self, xml: str, found: dict[int, LinkInfo]) -> int:
        soup = BeautifulSoup(xml, "xml")
        count = 0
        for item in soup.find_all("item"):           # RSS 2.0
            link = item.find("link")
            date_tag = item.find("pubDate") or item.find("date")
            date_hint = parse_rfc822(date_tag.get_text()) if date_tag else None
            if date_tag and not date_hint:
                date_hint = parse_any(date_tag.get_text())
            if link:
                self._add_link(found, link.get_text(strip=True) or link.get("href"), date_hint)
                count += 1
        for entry in soup.find_all("entry"):         # Atom
            link = entry.find("link")
            date_tag = entry.find("published") or entry.find("updated")
            if link:
                self._add_link(found, link.get("href"),
                               parse_iso(date_tag.get_text()) if date_tag else None)
                count += 1
        return count

    def _parse_sitemap(self, xml: str, found: dict[int, LinkInfo], depth: int = 0) -> None:
        soup = BeautifulSoup(xml, "xml")
        if soup.find("sitemapindex") and depth == 0:
            locs = [s.get_text(strip=True) for s in soup.select("sitemap > loc")]
            preferred = [u for u in locs if re.search(r"news|haber", u, re.I)] or locs[:1]
            for child in preferred[:3]:
                child_xml = self.http.get(child)
                if child_xml:
                    self._parse_sitemap(child_xml, found, depth + 1)
            return
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            date_tag = url_tag.find("publication_date") or url_tag.find("lastmod")
            if loc:
                self._add_link(found, loc.get_text(strip=True),
                               parse_iso(date_tag.get_text()) if date_tag else None)

    def discover(self) -> list[LinkInfo]:
        found: dict[int, LinkInfo] = {}

        for path in self.feed_paths:
            xml = self.http.get(urljoin(self.base_url + "/", path.lstrip("/")))
            if xml and ("<rss" in xml[:600] or "<feed" in xml[:600] or "<item" in xml):
                self._parse_feed(xml, found)

        for path in self.sitemap_paths:
            xml = self.http.get(urljoin(self.base_url + "/", path.lstrip("/")))
            if xml and ("<urlset" in xml or "<sitemapindex" in xml):
                self._parse_sitemap(xml, found)

        for path in self.listing_paths:
            html = self.http.get(urljoin(self.base_url + "/", path.lstrip("/")))
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                self._add_link(found, a["href"])

        links = sorted(found.values(), key=lambda l: l.article_id, reverse=True)
        self.report.links_found = len(links)
        return links

    # ----------------------------------------------------------- DETAY
    @staticmethod
    def _iter_ld_objects(data):
        if isinstance(data, list):
            for item in data:
                yield from BaseScraper._iter_ld_objects(item)
        elif isinstance(data, dict):
            if "@graph" in data:
                yield from BaseScraper._iter_ld_objects(data["@graph"])
            yield data

    def extract_jsonld(self, soup: BeautifulSoup) -> dict:
        """Sayfadaki NewsArticle JSON-LD nesnesini döndürür."""
        best: dict = {}
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text() or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw, strict=False)
            except json.JSONDecodeError:
                try:
                    data = json.loads(re.sub(r"[\r\n\t]+", " ", raw), strict=False)
                except json.JSONDecodeError:
                    continue
            for obj in self._iter_ld_objects(data):
                types = obj.get("@type")
                types = set(types) if isinstance(types, list) else {types}
                if types & NEWS_LD_TYPES and (obj.get("headline") or obj.get("articleBody")):
                    if "NewsArticle" in types or not best:
                        best = obj
        return best

    @staticmethod
    def _meta(soup: BeautifulSoup, *names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name}) \
                or soup.find("meta", attrs={"itemprop": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    def clean_title(self, title: str) -> str:
        title = re.sub(r"\s+", " ", title or "").strip()
        # "Başlık - Çağdaş Kocaeli Gazetesi" -> "Başlık"
        parts = re.split(r"\s[-|–]\s", title)
        if len(parts) > 1 and re.search(r"kocaeli|gazete|haber|yaka|asayiş|son dakika", parts[-1], re.I):
            title = " - ".join(parts[:-1])
        return title.strip()

    def extract_body_html(self, soup: BeautifulSoup) -> str:
        for selector in self.content_selectors:
            el = soup.select_one(selector)
            if el and len(el.get_text(" ", strip=True)) > 150:
                return str(el)
        # Genel yöntem: doğrudan altında en çok paragraf metni bulunan blok
        best, best_len = None, 0
        for el in soup.find_all(["article", "div", "section", "main"]):
            total = sum(len(p.get_text(" ", strip=True)) for p in el.find_all("p", recursive=False))
            if total > best_len:
                best, best_len = el, total
        if best is not None and best_len >= 150:
            return str(best)
        paragraphs = soup.find_all("p")
        return "".join(str(p) for p in paragraphs)

    def extract_date(self, soup: BeautifulSoup, ld: dict) -> datetime | None:
        candidates = [
            ld.get("datePublished"), ld.get("dateCreated"),
            self._meta(soup, "article:published_time", "datePublished", "pubdate",
                       "publish-date", "og:published_time"),
        ]
        for value in candidates:
            dt = parse_iso(value) if value else None
            if dt:
                return dt
        time_tag = soup.find("time")
        if time_tag:
            dt = parse_any(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
            if dt:
                return dt
        # Son çare: sayfanın üst kısmındaki ilk Türkçe tarih ifadesi
        text = soup.get_text(" ", strip=True)[:4000]
        return parse_turkish_date(text)

    def parse_article(self, url: str, html: str) -> RawArticle | None:
        soup = BeautifulSoup(html, "lxml")

        canonical_tag = soup.find("link", rel="canonical")
        canonical = self.normalize_url(canonical_tag.get("href")) if canonical_tag else None
        final_url = canonical if canonical and self.is_article_url(canonical) else url

        ld = self.extract_jsonld(soup)
        h1 = soup.find("h1")
        title = self.clean_title(
            ld.get("headline") or self._meta(soup, "og:title", "twitter:title")
            or (h1.get_text(" ", strip=True) if h1 else "")
        )
        if not title:
            return None

        body = ld.get("articleBody") or ""
        return RawArticle(
            url=final_url,
            discovered_url=url,
            site_name=self.site_name,
            title=title,
            published_at=self.extract_date(soup, ld),
            body_html=self.extract_body_html(soup),
            ld_body=body if isinstance(body, str) else "",
            description=ld.get("description") or self._meta(soup, "og:description", "description"),
        )

    # ----------------------------------------------------------- TARAMA
    def scrape(self, since: datetime, should_fetch: Callable[[str], bool],
               progress: Callable[[str], None] | None = None) -> list[ScrapeItem]:
        """`since` tarihinden yeni haberleri toplar."""
        self.report = SiteReport(self.site_name)
        items: list[ScrapeItem] = []
        try:
            links = self.discover()
        except Exception as exc:  # bir sitenin hatası diğerlerini durdurmamalı
            log.exception("%s keşif hatası", self.site_name)
            self.report.errors.append(f"keşif: {exc}")
            return items

        consecutive_old = 0
        for link in links:
            if self.report.fetched >= config.MAX_ARTICLES_PER_SITE:
                break
            if consecutive_old >= config.STOP_AFTER_OLD_ARTICLES:
                break
            if link.date_hint and link.date_hint < since:
                self.report.skipped_old_by_hint += 1
                consecutive_old += 1
                continue
            if not should_fetch(link.url):
                self.report.skipped_known += 1
                continue

            if progress:
                progress(f"{self.site_name}: {self.report.fetched + 1}. haber inceleniyor")
            html = self.http.get(link.url)
            self.report.fetched += 1
            if not html:
                items.append(ScrapeItem(link.url, self.site_name, error_status="fetch_failed",
                                        error="sayfa indirilemedi"))
                continue
            try:
                article = self.parse_article(link.url, html)
            except Exception as exc:
                log.exception("Ayrıştırma hatası: %s", link.url)
                items.append(ScrapeItem(link.url, self.site_name, error_status="parse_failed",
                                        error=str(exc)))
                continue
            if article is None:
                items.append(ScrapeItem(link.url, self.site_name, error_status="parse_failed",
                                        error="başlık bulunamadı"))
                continue
            if article.published_at is None:
                items.append(ScrapeItem(link.url, self.site_name, article=article,
                                        error_status="no_date", error="yayın tarihi bulunamadı"))
                continue

            consecutive_old = consecutive_old + 1 if article.published_at < since else 0
            items.append(ScrapeItem(article.url, self.site_name, article=article))
        return items
