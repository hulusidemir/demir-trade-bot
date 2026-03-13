"""
Trade Bot — Binance Exchange Adapter
Binance Futures (USDT-M) WebSocket & REST API entegrasyonu.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import List

import aiohttp
import websockets

from core.models import (
    FundingRateData,
    LiquidationData,
    OpenInterestData,
    OrderbookLevel,
    OrderbookSnapshot,
    TradeData,
)
from exchanges.base import BaseExchange

logger = logging.getLogger("exchange.binance")

WS_BASE = "wss://fstream.binance.com/ws"
REST_BASE = "https://fapi.binance.com"
SPOT_WS_BASE = "wss://stream.binance.com:9443/ws"


class BinanceExchange(BaseExchange):
    name = "binance"

    def _normalize_symbol(self, symbol: str) -> str:
        """BTC/USDT → btcusdt"""
        return symbol.replace("/", "").lower()

    def _rest_symbol(self, symbol: str) -> str:
        """BTC/USDT → BTCUSDT"""
        return symbol.replace("/", "").upper()

    # ── WebSocket: Futures Trades ─────────────────

    async def _ws_trades(self):
        streams = "/".join(f"{self._normalize_symbol(s)}@aggTrade" for s in self.symbols)
        url = f"{WS_BASE}/{streams}" if len(self.symbols) == 1 else f"wss://fstream.binance.com/stream?streams={streams}"

        async with websockets.connect(url, ping_interval=20) as ws:
            logger.info("[binance] Futures trade stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if "stream" in data:
                    data = data["data"]
                trade = TradeData(
                    exchange="binance",
                    symbol=data.get("s", ""),
                    price=float(data["p"]),
                    quantity=float(data["q"]),
                    is_buyer_maker=data["m"],
                    timestamp=data["T"] / 1000,
                )
                await self._emit_trade(trade)

    # ── WebSocket: Spot Trades (CVD ayrımı için) ──

    async def _ws_spot_trades(self, callback):
        streams = "/".join(f"{self._normalize_symbol(s)}@aggTrade" for s in self.symbols)
        url = f"{SPOT_WS_BASE}/{streams}" if len(self.symbols) == 1 else f"wss://stream.binance.com:9443/stream?streams={streams}"

        async with websockets.connect(url, ping_interval=20) as ws:
            logger.info("[binance] Spot trade stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if "stream" in data:
                    data = data["data"]
                trade = TradeData(
                    exchange="binance_spot",
                    symbol=data.get("s", ""),
                    price=float(data["p"]),
                    quantity=float(data["q"]),
                    is_buyer_maker=data["m"],
                    timestamp=data["T"] / 1000,
                )
                if callback:
                    await callback(trade)

    # ── WebSocket: Orderbook ──────────────────────

    async def _ws_orderbook(self):
        streams = "/".join(f"{self._normalize_symbol(s)}@depth20@100ms" for s in self.symbols)
        url = f"wss://fstream.binance.com/stream?streams={streams}"

        async with websockets.connect(url, ping_interval=20) as ws:
            logger.info("[binance] Orderbook stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if "stream" in data:
                    data = data["data"]
                ob = OrderbookSnapshot(
                    exchange="binance",
                    symbol=data.get("s", self.symbols[0].replace("/", "")),
                    bids=[OrderbookLevel(price=float(b[0]), quantity=float(b[1])) for b in data.get("b", [])],
                    asks=[OrderbookLevel(price=float(a[0]), quantity=float(a[1])) for a in data.get("a", [])],
                    timestamp=time.time(),
                )
                await self._emit_orderbook(ob)

    # ── WebSocket: Likidasyonlar ──────────────────

    async def _ws_liquidations(self):
        streams = "/".join(f"{self._normalize_symbol(s)}@forceOrder" for s in self.symbols)
        url = f"wss://fstream.binance.com/stream?streams={streams}"

        async with websockets.connect(url, ping_interval=20) as ws:
            logger.info("[binance] Likidasyon stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if "stream" in data:
                    data = data["data"]
                o = data.get("o", {})
                liq = LiquidationData(
                    exchange="binance",
                    symbol=o.get("s", ""),
                    side=o.get("S", ""),       # BUY veya SELL
                    price=float(o.get("p", 0)),
                    quantity=float(o.get("q", 0)),
                    timestamp=o.get("T", time.time() * 1000) / 1000,
                )
                await self._emit_liquidation(liq)

    # ── REST: Open Interest ───────────────────────

    async def _poll_open_interest(self) -> List[OpenInterestData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        url = f"{REST_BASE}/fapi/v1/openInterest?symbol={self._rest_symbol(sym)}"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            oi = OpenInterestData(
                                exchange="binance",
                                symbol=sym,
                                value=float(data.get("openInterest", 0)),
                                timestamp=time.time(),
                            )
                            # OI callback'i aggregator'da kayıtlı
                            if hasattr(self, "on_oi") and self.on_oi:
                                await self.on_oi(oi)
            except Exception as exc:
                logger.error("[binance] OI poll hatası: %s", exc)
            await asyncio.sleep(10)

    # ── REST: Funding Rate ────────────────────────

    async def _poll_funding_rate(self) -> List[FundingRateData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        url = f"{REST_BASE}/fapi/v1/premiumIndex?symbol={self._rest_symbol(sym)}"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            fr = FundingRateData(
                                exchange="binance",
                                symbol=sym,
                                rate=float(data.get("lastFundingRate", 0)),
                                next_funding_time=float(data.get("nextFundingTime", 0)) / 1000,
                                timestamp=time.time(),
                            )
                            if hasattr(self, "on_funding") and self.on_funding:
                                await self.on_funding(fr)
            except Exception as exc:
                logger.error("[binance] FR poll hatası: %s", exc)
            await asyncio.sleep(30)
