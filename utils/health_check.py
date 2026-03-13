"""
Trade Bot — Health Check / Servis Sağlık Kontrolü
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tüm dış servislere (borsalar, Telegram, CryptoPanic) ping atarak
bağlantı durumunu kontrol eder.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import aiohttp

from config import settings

logger = logging.getLogger("utils.health_check")

# ── Servis tanımları (ad → ping URL) ──────────────
EXCHANGE_HEALTH_ENDPOINTS: Dict[str, str] = {
    "binance": "https://fapi.binance.com/fapi/v1/ping",
    "bybit": "https://api.bybit.com/v5/market/time",
    "okx": "https://www.okx.com/api/v5/public/time",
    "coinbase": "https://api.coinbase.com/v2/time",
    "kraken": "https://api.kraken.com/0/public/Time",
}

CRYPTOPANIC_HEALTH = "https://cryptopanic.com/api/v1/posts/?auth_token={key}&limit=1"
TELEGRAM_HEALTH = "https://api.telegram.org/bot{token}/getMe"


@dataclass
class ServiceStatus:
    """Tek bir servisin sağlık durumu."""
    name: str
    reachable: bool
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class HealthReport:
    """Tüm servislerin sağlık raporu."""
    timestamp: float = field(default_factory=time.time)
    services: List[ServiceStatus] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(s.reachable for s in self.services)

    @property
    def failed_services(self) -> List[ServiceStatus]:
        return [s for s in self.services if not s.reachable]

    @property
    def ok_services(self) -> List[ServiceStatus]:
        return [s for s in self.services if s.reachable]

    def format_telegram_message(self) -> str:
        """Telegram'a göndermeye uygun formatlı rapor üret."""
        lines = ["🏥 SERVİS SAĞLIK KONTROLÜ", "━" * 30, ""]

        for svc in self.services:
            if svc.reachable:
                lines.append(f"  ✅ {svc.name}  —  {svc.latency_ms:.0f}ms")
            else:
                lines.append(f"  ❌ {svc.name}  —  ULAŞILAMIYOR")
                if svc.error:
                    lines.append(f"      └ Hata: {svc.error}")

        lines.append("")
        ok = len(self.ok_services)
        total = len(self.services)
        if self.all_ok:
            lines.append(f"📡 Sonuç: Tüm servisler aktif ({ok}/{total})")
        else:
            failed_names = ", ".join(s.name for s in self.failed_services)
            lines.append(f"⚠️ Sonuç: {ok}/{total} servis aktif")
            lines.append(f"❌ Ulaşılamayan: {failed_names}")

        return "\n".join(lines)


async def _ping_url(session: aiohttp.ClientSession, name: str, url: str,
                     timeout_sec: float = 10.0) -> ServiceStatus:
    """Tek bir URL'ye HTTP GET atıp durumu döndür."""
    t0 = time.monotonic()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as resp:
            latency = (time.monotonic() - t0) * 1000
            if resp.status < 500:
                return ServiceStatus(name=name, reachable=True, latency_ms=latency)
            else:
                body = await resp.text()
                return ServiceStatus(name=name, reachable=False, latency_ms=latency,
                                     error=f"HTTP {resp.status}")
    except asyncio.TimeoutError:
        return ServiceStatus(name=name, reachable=False,
                             error=f"Timeout ({timeout_sec}s)")
    except aiohttp.ClientConnectorError as e:
        return ServiceStatus(name=name, reachable=False,
                             error=f"Bağlantı hatası: {e}")
    except Exception as e:
        return ServiceStatus(name=name, reachable=False,
                             error=str(e)[:120])


async def run_health_check() -> HealthReport:
    """
    Tüm servislere paralel ping atıp HealthReport döndürür.
    Active exchanges listesindeki borsalar + Telegram + CryptoPanic.
    """
    report = HealthReport()

    async with aiohttp.ClientSession() as session:
        tasks = []

        # 1. Telegram
        if settings.telegram.bot_token:
            url = TELEGRAM_HEALTH.format(token=settings.telegram.bot_token)
            tasks.append(_ping_url(session, "Telegram Bot API", url))
        else:
            report.services.append(
                ServiceStatus(name="Telegram Bot API", reachable=False,
                              error="Token ayarlanmamış")
            )

        # 2. Aktif borsalar
        for ex_name in settings.active_exchanges:
            url = EXCHANGE_HEALTH_ENDPOINTS.get(ex_name)
            if url:
                display = ex_name.capitalize()
                tasks.append(_ping_url(session, display, url))

        # 3. CryptoPanic
        if settings.news.cryptopanic_api_key:
            url = CRYPTOPANIC_HEALTH.format(key=settings.news.cryptopanic_api_key)
            tasks.append(_ping_url(session, "CryptoPanic", url))
        else:
            report.services.append(
                ServiceStatus(name="CryptoPanic", reachable=False,
                              error="API key ayarlanmamış")
            )

        # Paralel çalıştır
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, ServiceStatus):
                    report.services.append(r)
                elif isinstance(r, Exception):
                    report.services.append(
                        ServiceStatus(name="Bilinmeyen", reachable=False,
                                      error=str(r)[:120])
                    )

    return report


async def ping_single_service(name: str, url: str,
                               timeout_sec: float = 10.0) -> ServiceStatus:
    """Tek bir servise ping at — runtime monitoring için."""
    async with aiohttp.ClientSession() as session:
        return await _ping_url(session, name, url, timeout_sec)
