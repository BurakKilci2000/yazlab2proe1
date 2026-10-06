from datetime import datetime, timedelta, timezone

from scraper.base import BaseScraper
from scraper.dates import parse_iso, parse_rfc822, parse_turkish_date
from scraper.sites import ALL_SCRAPERS
from scraper.sites.seskocaeli import SesKocaeliScraper
from scraper.sites.yenikocaeli import YeniKocaeliScraper


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return self.pages.get(url)


def test_five_sources_are_registered():
    names = {cls.site_name for cls in ALL_SCRAPERS}
    assert names == {"Çağdaş Kocaeli", "Özgür Kocaeli", "Ses Kocaeli", "Yeni Kocaeli", "Bizim Yaka"}


def test_dates():
    assert parse_iso("2026-09-22T16:18:00+03:00") == datetime(2026, 9, 22, 13, 18, tzinfo=timezone.utc)
    assert parse_rfc822("Tue, 22 Sep 2026 16:18:00 +0300").hour == 13
    assert parse_turkish_date("04 Eyl 2026 - 12:43 Kocaeli") == datetime(2026, 9, 4, 9, 43, tzinfo=timezone.utc)
    assert parse_turkish_date("19 Nisan 2024 Cuma") == datetime(2024, 4, 18, 21, 0, tzinfo=timezone.utc)
    assert parse_turkish_date("18.09.2026 15:59").hour == 12


def test_link_discovery_filters_and_normalizes(fixture_html):
    s = SesKocaeliScraper(http=FakeHttp({}))
    found = {}
    from bs4 import BeautifulSoup
    for a in BeautifulSoup(fixture_html("listing.html"), "lxml").find_all("a", href=True):
        s._add_link(found, a["href"])
    urls = sorted(l.url for l in found.values())
    assert urls == [
        "https://www.seskocaeli.com/foto/28652258/kandira-yolunda-feci-kaza",
        "https://www.seskocaeli.com/haber/28651700/kmoda-zincirleme-kaza",
        "https://www.seskocaeli.com/haber/28859315/tramvay-yolunda-kaza",
    ]


def test_parse_cms_article(fixture_html):
    s = SesKocaeliScraper(http=FakeHttp({}))
    art = s.parse_article("https://www.seskocaeli.com/haber/28434759/x", fixture_html("cms_article.html"))
    assert art.url == "https://www.seskocaeli.com/haber/28434759/kaza-yapan-otomobil-surucusu-bayginlik-gecirdi"
    assert art.title == "Kaza yapan otomobil sürücüsü baygınlık geçirdi!"
    assert art.published_at == datetime(2026, 7, 30, 16, 59, tzinfo=timezone.utc)
    assert "Akşemsettin Caddesi" in art.body_html
    assert art.description.startswith("Körfez'de iki otomobil")


def test_parse_other_cms_without_jsonld(fixture_html):
    s = YeniKocaeliScraper(http=FakeHttp({}))
    art = s.parse_article("https://www.yenikocaeli.com/haber/polis-adliye/x/1.html", fixture_html("yeni_article.html"))
    assert art.title == "Gebze'de evden hırsızlık"
    assert art.published_at == datetime(2019, 5, 8, 16, 45, tzinfo=timezone.utc)
    assert "Osman Yılmaz Mahallesi" in art.body_html
    assert s.is_article_url("https://www.yenikocaeli.com/muhabir/rabia/haber/polis-adliye/x-y/173034.html")
    assert not s.is_article_url("https://www.yenikocaeli.com/haber/cinayet.html")


def test_scrape_respects_date_window_and_known_links(fixture_html):
    now = datetime.now(timezone.utc)
    fresh = fixture_html("cms_article.html").replace("2026-07-30T19:59:00+03:00", now.isoformat())
    base = "https://www.seskocaeli.com"
    rss = f"""<?xml version="1.0"?><rss><channel>
      <item><link>{base}/haber/30000003/yeni</link><pubDate>{(now - timedelta(hours=2)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>
      <item><link>{base}/haber/30000002/bilinen</link></item>
      <item><link>{base}/haber/10000001/eski</link><pubDate>Mon, 01 Jan 2024 10:00:00 +0300</pubDate></item>
    </channel></rss>"""
    http = FakeHttp({f"{base}/rss": rss, f"{base}/haber/30000003/yeni": fresh})

    class TestScraper(SesKocaeliScraper):
        feed_paths = ("/rss",)
        sitemap_paths = ()
        listing_paths = ()

    s = TestScraper(http=http)
    items = s.scrape(now - timedelta(days=3), should_fetch=lambda url: "bilinen" not in url)
    assert len(items) == 1 and items[0].article is not None
    assert f"{base}/haber/10000001/eski" not in http.requested     # RSS tarihine göre atlandı
    assert s.report.skipped_known == 1 and s.report.skipped_old_by_hint == 1
