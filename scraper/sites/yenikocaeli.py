"""
Yeni Kocaeli (https://www.yenikocaeli.com) scraper'ı.

Bu site farklı bir yazılım kullanır. Haber adresleri:
    /haber/polis-adliye/izmitte-intihar-girisimi/131336.html
    /muhabir/rabia/haber/polis-adliye/.../173034.html   (aynı haberin muhabir yolu)
Etiket sayfaları ise /haber/<etiket>.html biçimindedir.
"""
from __future__ import annotations

import re

from scraper.base import BaseScraper


class YeniKocaeliScraper(BaseScraper):
    site_name = "Yeni Kocaeli"
    base_url = "https://www.yenikocaeli.com"
    feed_paths = ("/rss.xml", "/rss", "/rss/son-dakika.xml")
    listing_paths = (
        "/", "/haber/polis-adliye.html", "/haber/guncel.html", "/haber/yasam.html",
        "/haber/kultur-sanat.html", "/haber/yangin.html", "/haber/kaza.html",
        "/haber/trafik-kazasi.html", "/haber/hirsizlik.html",
        "/haber/elektrik-kesintisi.html", "/haber/konser.html",
    )
    article_path_regex = re.compile(
        r"^(?:/muhabir/[a-z0-9-]+)?/haber/[a-z0-9-]+/[a-z0-9-]+/(\d+)\.html$"
    )
    content_selectors = (
        "div[itemprop='articleBody']", "div[property='articleBody']",
        "div.news-text", "div.haber-metni", "div.detail-content", "div.content-text",
    )
