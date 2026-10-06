"""
Çağdaş Kocaeli, Özgür Kocaeli, Ses Kocaeli ve Bizim Yaka aynı haber yazılımını
(CMS) kullanır. Haber adresleri şu kalıptadır:
    /haber/28834391/izmitte-iki-aracin-karistigi-kaza-trafigi-etkiledi
    /foto/28585133/kartepe-d100-askeriye-sapagi-otomobil-kamyonet-kaza
    /video/17663580/...
Ortak davranış bu sınıfta, siteye özel ad/adres alt sınıflarda tanımlanır.
"""
from __future__ import annotations

import re

from scraper.base import BaseScraper

# Etiket sayfaları (/haberleri/<etiket>) haber türlerine göre filtrelenmiş liste verir.
TAG_PAGES = (
    "/haberleri/kaza", "/haberleri/trafik-kazasi", "/haberleri/yangin",
    "/haberleri/hirsizlik", "/haberleri/hirsiz", "/haberleri/elektrik-kesintisi",
    "/haberleri/sedas", "/haberleri/konser", "/haberleri/tiyatro",
    "/haberleri/festival", "/haberleri/sergi", "/haberleri/etkinlik",
)


class CommonCmsScraper(BaseScraper):
    feed_paths = ("/rss", "/rss/son-dakika", "/rss/asayis", "/rss/kultur-sanat")
    listing_paths = ("/", "/son-dakika-haberleri", "/asayis", "/gundem",
                     "/kultur-sanat", "/yasam") + TAG_PAGES
    article_path_regex = re.compile(r"^/(?:haber|foto|video)/(\d{5,})/[a-z0-9-]+$")
    content_selectors = (
        "div[property='articleBody']", "div[itemprop='articleBody']",
        "div.article-text", "div.content-text", "div.news-content",
        "div.text-content", "article .article-body",
    )
