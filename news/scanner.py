"""
Trade Bot — News / Macro Event Scanner
CryptoPanic API + RSS ile son 1 saatlik kritik haberleri tarar.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import aiohttp

from config import settings

logger = logging.getLogger("news.scanner")


@dataclass
class NewsItem:
    title: str
    source: str
    url: str
    kind: str           # "news" | "media" | "macro"
    is_critical: bool   # Makro/hack/unlock vb.
    timestamp: float = field(default_factory=time.time)
    currencies: List[str] = field(default_factory=list)


class NewsScanner:
    """
    Haber tarayıcı.
    - CryptoPanic API (public)
    - Makro olay filtreleme (TÜFE, FOMC, Hack, Token Unlock vb.)
    """

    CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"

    def __init__(self):
        self._api_key = settings.news.cryptopanic_api_key
        self._keywords = settings.news.macro_keywords
        self._cache: List[NewsItem] = []
        self._last_scan: float = 0

    async def start_scanning(self):
        """Periyodik haber tarama döngüsü."""
        logger.info("Haber tarayıcı başlatılıyor…")
        while True:
            try:
                await self._scan()
            except Exception as exc:
                logger.error("Haber tarama hatası: %s", exc)
            await asyncio.sleep(settings.news.scan_interval_sec)

    async def _scan(self):
        """CryptoPanic API'den son haberleri çek."""
        if not self._api_key:
            logger.debug("CryptoPanic API key yok, atlanıyor.")
            return

        params = {
            "auth_token": self._api_key,
            "kind": "news",
            "filter": "hot",
            "public": "true",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.CRYPTOPANIC_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.warning("CryptoPanic API %d döndü.", resp.status)
                        return

                    data = await resp.json()
                    results = data.get("results", [])

                    items = []
                    for r in results:
                        title = r.get("title", "")
                        is_critical = any(
                            kw.lower() in title.lower() for kw in self._keywords
                        )
                        currencies = [
                            c.get("code", "") for c in r.get("currencies", [])
                        ]

                        item = NewsItem(
                            title=title,
                            source=r.get("source", {}).get("title", ""),
                            url=r.get("url", ""),
                            kind=r.get("kind", "news"),
                            is_critical=is_critical,
                            currencies=currencies,
                        )
                        items.append(item)

                    self._cache = items
                    self._last_scan = time.time()
                    logger.info(
                        "Haber taraması tamamlandı: %d haber, %d kritik.",
                        len(items), sum(1 for i in items if i.is_critical),
                    )

        except Exception as exc:
            logger.error("CryptoPanic fetch hatası: %s", exc)

    def get_context(self, symbol: str = "") -> str:
        """
        Sinyal mesajı için haber bağlamı döndür.
        """
        if not self._cache:
            return "Son 1 saatte kritik haber tespit edilmedi."

        # Sembolle ilgili haberler
        coin = symbol.split("/")[0].upper() if symbol else ""
        relevant = []
        critical = []

        for item in self._cache:
            if item.is_critical:
                critical.append(item)
            if coin and coin in [c.upper() for c in item.currencies]:
                relevant.append(item)

        parts = []

        if critical:
            c = critical[0]
            parts.append(f"⚠️ MAKRO: {c.title} ({c.source})")

        if relevant:
            r = relevant[0]
            parts.append(f"📰 {coin}: {r.title} ({r.source})")

        if not parts:
            parts.append("Son 1 saatte kritik haber tespit edilmedi.")

        return " | ".join(parts)

    def has_macro_risk(self) -> Optional[str]:
        """
        Makro risk var mı? (TÜFE, FOMC, Hack vb.)
        Varsa uyarı metnini döndürür.
        """
        for item in self._cache:
            if item.is_critical:
                return f"Makro uyarı: {item.title}"
        return None
