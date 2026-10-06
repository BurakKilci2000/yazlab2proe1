"""Ses Kocaeli (https://www.seskocaeli.com) scraper'ı."""
from scraper.sites.common_cms import CommonCmsScraper


class SesKocaeliScraper(CommonCmsScraper):
    site_name = "Ses Kocaeli"
    base_url = "https://www.seskocaeli.com"
