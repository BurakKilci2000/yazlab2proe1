"""Özgür Kocaeli (https://www.ozgurkocaeli.com.tr) scraper'ı."""
from scraper.sites.common_cms import CommonCmsScraper


class OzgurKocaeliScraper(CommonCmsScraper):
    site_name = "Özgür Kocaeli"
    base_url = "https://www.ozgurkocaeli.com.tr"
