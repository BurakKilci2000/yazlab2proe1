"""
Haber sitelerine istek atan HTTP istemcisi.

- Gerçek bir tarayıcı gibi başlık (User-Agent, Accept-Language) gönderir.
- İstekler arasında bekler (siteleri yormamak ve engellenmemek için).
- Ağ hatalarında 3 kez dener.
- Site 403/429/503 ile bot koruması uygularsa, curl_cffi kuruluysa gerçek
  Chrome'un TLS parmak izini taklit ederek bir kez daha dener.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

import config

try:  # isteğe bağlı yedek istemci
    from curl_cffi import requests as cffi_requests
except Exception:  # pragma: no cover - kurulu değilse sorun değil
    cffi_requests = None

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.6",
}
BLOCK_CODES = {403, 429, 503}


class HttpClient:
    def __init__(self, delay: float = config.REQUEST_DELAY_SECONDS,
                 timeout: int = config.REQUEST_TIMEOUT, retries: int = 3):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0
        self._lock = threading.Lock()

    def _wait_turn(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self._last_request = time.monotonic()

    @staticmethod
    def _decode(response) -> str:
        # Bazı siteler karakter setini bildirmez; requests bunu ISO-8859-1 sanar
        # ve Türkçe karakterler bozulur. Bu durumda içerikten tahmin ederiz.
        enc = (response.encoding or "").lower()
        if not enc or enc == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def _get_with_browser_fingerprint(self, url: str) -> str | None:
        if cffi_requests is None:
            return None
        try:
            r = cffi_requests.get(url, impersonate="chrome", timeout=self.timeout,
                                  headers={"Accept-Language": DEFAULT_HEADERS["Accept-Language"]})
            if r.status_code == 200:
                return r.text
            log.warning("Yedek istemci de başarısız (%s): %s", r.status_code, url)
        except Exception as exc:
            log.warning("Yedek istemci hatası: %s (%s)", url, exc)
        return None

    def get(self, url: str) -> str | None:
        for attempt in range(1, self.retries + 1):
            self._wait_turn()
            try:
                r = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                log.warning("İstek hatası (%d/%d) %s: %s", attempt, self.retries, url, exc)
                time.sleep(1.5 * attempt)
                continue

            if r.status_code == 200:
                return self._decode(r)
            if r.status_code == 404:
                return None
            if r.status_code in BLOCK_CODES:
                html = self._get_with_browser_fingerprint(url)
                if html:
                    return html
            log.warning("HTTP %s (%d/%d): %s", r.status_code, attempt, self.retries, url)
            time.sleep(1.5 * attempt)
        return None
