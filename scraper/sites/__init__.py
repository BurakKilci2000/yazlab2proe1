"""Proje dokümanında verilen 5 yerel haber kaynağı."""
from scraper.sites.bizimyaka import BizimYakaScraper
from scraper.sites.cagdaskocaeli import CagdasKocaeliScraper
from scraper.sites.ozgurkocaeli import OzgurKocaeliScraper
from scraper.sites.seskocaeli import SesKocaeliScraper
from scraper.sites.yenikocaeli import YeniKocaeliScraper

ALL_SCRAPERS = (
    CagdasKocaeliScraper,
    OzgurKocaeliScraper,
    SesKocaeliScraper,
    YeniKocaeliScraper,
    BizimYakaScraper,
)
