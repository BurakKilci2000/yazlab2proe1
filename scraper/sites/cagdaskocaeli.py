"""Çağdaş Kocaeli (https://www.cagdaskocaeli.com.tr) scraper'ı."""
from scraper.sites.common_cms import CommonCmsScraper


class CagdasKocaeliScraper(CommonCmsScraper):
    site_name = "Çağdaş Kocaeli"
    base_url = "https://www.cagdaskocaeli.com.tr"
