"""
Trade Bot — Base Exchange Adapter
Tüm borsa adaptörleri bu soyut sınıftan türer.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional

from core.models import (
    FundingRateData,
    LiquidationData,
    OpenInterestData,
    OrderbookSnapshot,
    TradeData,
)

logger = logging.getLogger("exchange.base")

# Callback tipleri
TradeCallback = Callable[[TradeData], Coroutine[Any, Any, None]]
OrderbookCallback = Callable[[OrderbookSnapshot], Coroutine[Any, Any, None]]
LiquidationCallback = Callable[[LiquidationData], Coroutine[Any, Any, None]]


class BaseExchange(ABC):
    """Her borsa adaptörünün implemente etmesi gereken arayüz."""

    name: str = "base"

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # Callbacks — aggregator tarafından set edilir
        self.on_trade: Optional[TradeCallback] = None
        self.on_orderbook: Optional[OrderbookCallback] = None
        self.on_liquidation: Optional[LiquidationCallback] = None

    # ── Lifecycle ──────────────────────────────────

    async def start(self):
        """Tüm WS akışlarını başlat."""
        self._running = True
        logger.info("[%s] Başlatılıyor… Semboller: %s", self.name, self.symbols)
        self._tasks = [
            asyncio.create_task(self._safe(self._ws_trades)),
            asyncio.create_task(self._safe(self._ws_orderbook)),
            asyncio.create_task(self._safe(self._ws_liquidations)),
            asyncio.create_task(self._safe(self._poll_open_interest)),
            asyncio.create_task(self._safe(self._poll_funding_rate)),
        ]

    async def stop(self):
        """Tüm görevleri iptal et."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        logger.info("[%s] Durduruldu.", self.name)

    # Tüm WS bağlantıları için ortak parametreler
    WS_KWARGS = {
        "ping_interval": 25,
        "ping_timeout": 60,
        "close_timeout": 5,
        "max_size": 2**22,  # 4 MB
    }

    async def _safe(self, coro_func):
        """Hata yakalayıcı wrapper — bir stream çökerse yeniden başlatır."""
        while self._running:
            try:
                await coro_func()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("[%s] %s bağlantı koptu, 3s sonra yeniden bağlanılacak.", self.name, coro_func.__name__)
                await asyncio.sleep(3)

    # ── WebSocket Akışları (Alt sınıflar implemente eder) ──

    @abstractmethod
    async def _ws_trades(self):
        """Gerçek zamanlı trade akışı."""
        ...

    @abstractmethod
    async def _ws_orderbook(self):
        """Gerçek zamanlı emir defteri akışı."""
        ...

    @abstractmethod
    async def _ws_liquidations(self):
        """Gerçek zamanlı likidasyon akışı."""
        ...

    # ── REST Polling (Alt sınıflar implemente eder) ──

    @abstractmethod
    async def _poll_open_interest(self) -> List[OpenInterestData]:
        """Periyodik OI çekimi (her 5-10 sn)."""
        ...

    @abstractmethod
    async def _poll_funding_rate(self) -> List[FundingRateData]:
        """Periyodik Funding Rate çekimi."""
        ...

    # ── Yardımcılar ──

    def _normalize_symbol(self, symbol: str) -> str:
        """Borsa-spesifik sembol format dönüşümü. Alt sınıflar override edebilir."""
        return symbol

    async def _emit_trade(self, trade: TradeData):
        if self.on_trade:
            await self.on_trade(trade)

    async def _emit_orderbook(self, ob: OrderbookSnapshot):
        if self.on_orderbook:
            await self.on_orderbook(ob)

    async def _emit_liquidation(self, liq: LiquidationData):
        if self.on_liquidation:
            await self.on_liquidation(liq)
