"""
Trade Bot — Engine (Orchestrator)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tüm bileşenleri birbirine bağlayan ana orkestratör.
Exchange adaptörleri ↔ Aggregator ↔ SignalManager ↔ TelegramBot
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
import traceback
from typing import List, Optional

from config import settings
from core.aggregator import Aggregator
from exchanges.base import BaseExchange
from exchanges.binance_ex import BinanceExchange
from exchanges.bybit_ex import BybitExchange
from exchanges.coinbase_ex import CoinbaseExchange
from exchanges.kraken_ex import KrakenExchange
from exchanges.okx_ex import OKXExchange
from exchanges.symbol_fetcher import fetch_all_bybit_symbols
from news.scanner import NewsScanner
from telegram.bot import TelegramBot
from core.models import Signal
from utils.health_check import (
    run_health_check,
    ping_single_service,
    EXCHANGE_HEALTH_ENDPOINTS,
    HealthReport,
    ServiceStatus,
)

logger = logging.getLogger("core.engine")

# Borsa sınıfları registry
EXCHANGE_CLASSES = {
    "binance": BinanceExchange,
    "bybit": BybitExchange,
    "okx": OKXExchange,
    "coinbase": CoinbaseExchange,
    "kraken": KrakenExchange,
}

# Runtime health check aralığı (saniye)
_RUNTIME_HEALTH_INTERVAL = 120  # 2 dakikada bir


class Engine:
    """
    Ana orkestratör.
    Sistemi başlatır, tüm bileşenleri bağlar ve async event loop'u yönetir.
    """

    def __init__(self):
        self.aggregator = Aggregator()
        self.telegram = TelegramBot()
        self.news_scanner = NewsScanner()
        self.exchanges: List[BaseExchange] = []

        # Shutdown sebebi takibi
        self._shutdown_reason: str = "Bilinmeyen sebep"
        self._shutdown_detail: str = ""
        self._start_time: float = 0.0

        # Runtime health — son bilinen durumlar
        self._last_health: Optional[HealthReport] = None

    # ══════════════════════════════════════════════
    #  Başlatma
    # ══════════════════════════════════════════════

    async def start(self):
        """Tüm sistemi başlat."""
        self._start_time = time.time()

        # 0. Auto-symbol modu: Bybit'ten tüm sembolleri çek
        if settings.is_auto_symbols:
            logger.info("Auto-symbol modu aktif — Bybit sembol listesi çekiliyor…")
            try:
                fetched = await fetch_all_bybit_symbols()
            except Exception as exc:
                self._shutdown_reason = "Başlatma hatası"
                self._shutdown_detail = f"Bybit sembol çekimi başarısız: {exc}"
                await self._send_shutdown_message()
                return
            if fetched:
                settings.symbols = fetched
                logger.info("%d USDT perp sembol bulundu.", len(fetched))
            else:
                self._shutdown_reason = "Başlatma hatası"
                self._shutdown_detail = "Bybit'ten sembol çekilemedi (boş liste)."
                await self._send_shutdown_message()
                return

        logger.info("=" * 60)
        logger.info("  TRADE BOT BAŞLATILIYOR")
        logger.info("  Semboller: %d adet", len(settings.symbols))
        logger.info("  Borsalar: %s", settings.active_exchanges)
        logger.info("=" * 60)

        # 1. Sağlık kontrolü — tüm servislere ping
        logger.info("Servis sağlık kontrolü yapılıyor…")
        health = await run_health_check()
        self._last_health = health

        # 2. Exchange adaptörlerini oluştur ve bağla
        self._init_exchanges()

        # 3. Sinyal callback'ini bağla
        self.aggregator.on_signal = self._on_signal

        # 4. Başlangıç mesajını oluştur ve gönder
        startup_msg = self._build_startup_message(health)
        await self.telegram.send_alert(startup_msg)

        if not health.all_ok:
            failed = ", ".join(s.name for s in health.failed_services)
            logger.warning("Bazı servisler ulaşılamaz: %s — bot yine de çalışacak.", failed)

        # 5. Tüm async görevleri başlat
        tasks = []

        # Exchange WS stream'leri
        for ex in self.exchanges:
            tasks.append(asyncio.create_task(ex.start()))

        # Aggregator evaluation loop
        tasks.append(asyncio.create_task(
            self.aggregator.run_evaluation_loop(interval_sec=5.0)
        ))

        # Haber tarayıcı
        tasks.append(asyncio.create_task(
            self.news_scanner.start_scanning()
        ))

        # Runtime sağlık monitörü
        tasks.append(asyncio.create_task(
            self._runtime_health_monitor()
        ))

        logger.info("Tüm bileşenler başlatıldı. Sinyal bekleniyor…")

        # Sonsuza kadar çalış
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self._shutdown_reason = "Kullanıcı durdurması"
            self._shutdown_detail = "SIGINT / SIGTERM / task cancel"
        except Exception as exc:
            self._shutdown_reason = "Beklenmeyen hata"
            self._shutdown_detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-300:]}"
            logger.exception("Engine'de beklenmeyen hata!")
        finally:
            await self._shutdown()

    # ══════════════════════════════════════════════
    #  Başlangıç Mesajı
    # ══════════════════════════════════════════════

    def _build_startup_message(self, health: HealthReport) -> str:
        """Detaylı başlangıç ve sağlık durumu Telegram mesajı."""
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        sym_summary = (
            f"{len(settings.symbols)} sembol (auto-scan)"
            if settings.is_auto_symbols
            else ", ".join(settings.symbols[:10])
        )

        lines = [
            "🚀 TRADE BOT BAŞLATILDI",
            "━" * 30,
            "",
            f"⏰ Zaman: {now_str}",
            f"📊 Semboller: {sym_summary}",
            f"🏦 Borsalar: {', '.join(settings.active_exchanges)}",
            f"🎯 Min Güven: {settings.thresholds.min_signal_confidence * 100:.0f}%",
            "",
            "🏥 SERVİS BAĞLANTI DURUMU:",
            "─" * 30,
        ]

        for svc in health.services:
            if svc.reachable:
                lines.append(f"  ✅ {svc.name}  —  {svc.latency_ms:.0f}ms")
            else:
                lines.append(f"  ❌ {svc.name}  —  ULAŞILAMIYOR")
                if svc.error:
                    lines.append(f"      └ {svc.error}")

        lines.append("")
        ok = len(health.ok_services)
        total = len(health.services)
        if health.all_ok:
            lines.append(f"📡 Tüm servisler aktif ({ok}/{total}) ✅")
        else:
            lines.append(f"⚠️ {ok}/{total} servis aktif — bot çalışmaya devam edecek")

        lines.append("━" * 30)
        return "\n".join(lines)

    # ══════════════════════════════════════════════
    #  Shutdown & Sebep Takibi
    # ══════════════════════════════════════════════

    def set_shutdown_reason(self, reason: str, detail: str = ""):
        """Dışarıdan (main.py vb.) shutdown sebebi ayarlamak için."""
        self._shutdown_reason = reason
        self._shutdown_detail = detail

    async def _shutdown(self):
        """Tüm bileşenleri durdur ve sebep mesajı gönder."""
        logger.info("Shutdown başlatılıyor… Sebep: %s", self._shutdown_reason)

        # Exchange bağlantılarını kapat
        for ex in self.exchanges:
            try:
                await ex.stop()
            except Exception:
                pass

        # Shutdown mesajını gönder
        await self._send_shutdown_message()
        logger.info("Shutdown tamamlandı.")

    async def _send_shutdown_message(self):
        """Detaylı shutdown Telegram mesajı."""
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Uptime hesapla
        if self._start_time > 0:
            uptime_sec = time.time() - self._start_time
            hrs, rem = divmod(int(uptime_sec), 3600)
            mins, secs = divmod(rem, 60)
            uptime_str = f"{hrs}s {mins}dk {secs}sn"
        else:
            uptime_str = "—"

        lines = [
            "🛑 TRADE BOT DURDURULDU",
            "━" * 30,
            "",
            f"⏰ Zaman: {now_str}",
            f"⏱ Çalışma süresi: {uptime_str}",
            "",
            f"📌 Sebep: {self._shutdown_reason}",
        ]

        if self._shutdown_detail:
            # Detayı max 500 karakterle sınırla
            detail = self._shutdown_detail[:500]
            lines.append(f"📋 Detay: {detail}")

        lines.extend(["", "━" * 30])

        try:
            await self.telegram.send_alert("\n".join(lines))
        except Exception as exc:
            logger.error("Shutdown mesajı gönderilemedi: %s", exc)

    # ══════════════════════════════════════════════
    #  Runtime Sağlık Monitörü
    # ══════════════════════════════════════════════

    async def _runtime_health_monitor(self):
        """
        Periyodik olarak tüm servisleri kontrol et.
        Ulaşılamayan servis tespit edildiğinde Telegram'a bildirim gönder.
        Servis tekrar geldiğinde de bildirim gönder.
        """
        # İlk kontrolü atla — startup'ta zaten yapıldı
        await asyncio.sleep(_RUNTIME_HEALTH_INTERVAL)

        # Her servisin son bilinen durumu
        last_status: dict[str, bool] = {}
        if self._last_health:
            for svc in self._last_health.services:
                last_status[svc.name] = svc.reachable

        while True:
            try:
                health = await run_health_check()
                self._last_health = health

                for svc in health.services:
                    prev = last_status.get(svc.name)

                    if prev is True and not svc.reachable:
                        # Servis düştü — acil bildirim
                        err_info = f" ({svc.error})" if svc.error else ""
                        msg = (
                            f"🔴 SERVİS UYARISI\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"❌ {svc.name} servisine ULAŞILAMIYOR{err_info}\n"
                            f"⏰ {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S UTC')}\n"
                            f"ℹ️ İlgili veri akışı kesintili olabilir."
                        )
                        logger.warning("Servis ulaşılamaz: %s — %s", svc.name, svc.error)
                        await self.telegram.send_alert(msg)

                    elif prev is False and svc.reachable:
                        # Servis geri geldi — bildirim
                        msg = (
                            f"🟢 SERVİS DÜZELME\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"✅ {svc.name} servisi tekrar aktif ({svc.latency_ms:.0f}ms)\n"
                            f"⏰ {datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S UTC')}"
                        )
                        logger.info("Servis geri geldi: %s", svc.name)
                        await self.telegram.send_alert(msg)

                    last_status[svc.name] = svc.reachable

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Runtime health check hatası: %s", exc)

            await asyncio.sleep(_RUNTIME_HEALTH_INTERVAL)

    # ══════════════════════════════════════════════
    #  Exchange ve Sinyal
    # ══════════════════════════════════════════════

    def _init_exchanges(self):
        """Exchange adaptörlerini oluştur ve callback'leri bağla."""
        for name in settings.active_exchanges:
            cls = EXCHANGE_CLASSES.get(name)
            if not cls:
                logger.warning("Bilinmeyen borsa: %s, atlanıyor.", name)
                continue

            ex = cls(symbols=settings.symbols)

            # Data callback'leri bağla
            ex.on_trade = self.aggregator.on_trade
            ex.on_orderbook = self.aggregator.on_orderbook
            ex.on_liquidation = self.aggregator.on_liquidation

            # OI ve FR callback'leri
            ex.on_oi = self.aggregator.on_open_interest
            ex.on_funding = self.aggregator.on_funding_rate

            self.exchanges.append(ex)
            logger.info("Exchange yüklendi: %s", name)

    async def _on_signal(self, signal: Signal):
        """Sinyal geldiğinde Telegram'a gönder."""
        # Haber bağlamı ekle
        news_context = self.news_scanner.get_context(signal.symbol)

        # Makro risk kontrolü
        macro_risk = self.news_scanner.has_macro_risk()
        if macro_risk and not signal.alert_note:
            signal.alert_note = macro_risk + " — Riski düşür!"

        # Telegram'a gönder
        await self.telegram.send_signal(signal, news_context=news_context)

