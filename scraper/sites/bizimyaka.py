"""Bizim Yaka (https://www.bizimyaka.com) scraper'ı."""
from scraper.sites.common_cms import CommonCmsScraper


class BizimYakaScraper(CommonCmsScraper):
    site_name = "Bizim Yaka"
    base_url = "https://www.bizimyaka.com"
