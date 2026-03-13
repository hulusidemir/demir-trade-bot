"""
Trade Bot — Bybit Exchange Adapter
Bybit V5 API — Unified account, Linear USDT perps.
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

logger = logging.getLogger("exchange.bybit")

WS_LINEAR = "wss://stream.bybit.com/v5/public/linear"
WS_SPOT = "wss://stream.bybit.com/v5/public/spot"
REST_BASE = "https://api.bybit.com"


class BybitExchange(BaseExchange):
    name = "bybit"

    def _normalize_symbol(self, symbol: str) -> str:
        """BTC/USDT → BTCUSDT"""
        return symbol.replace("/", "")

    # ── WebSocket: Futures Trades ─────────────────

    async def _ws_trades(self):
        subs = [f"publicTrade.{self._normalize_symbol(s)}" for s in self.symbols]
        async with websockets.connect(WS_LINEAR, **self.WS_KWARGS) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": subs}))
            logger.info("[bybit] Futures trade stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("topic", "").startswith("publicTrade"):
                    for t in data.get("data", []):
                        trade = TradeData(
                            exchange="bybit",
                            symbol=t["s"],
                            price=float(t["p"]),
                            quantity=float(t["v"]),
                            is_buyer_maker=(t["S"] == "Sell"),
                            timestamp=float(t["T"]) / 1000,
                        )
                        await self._emit_trade(trade)

    # ── WebSocket: Orderbook ──────────────────────

    async def _ws_orderbook(self):
        subs = [f"orderbook.50.{self._normalize_symbol(s)}" for s in self.symbols]
        async with websockets.connect(WS_LINEAR, **self.WS_KWARGS) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": subs}))
            logger.info("[bybit] Orderbook stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if "orderbook" in data.get("topic", ""):
                    d = data["data"]
                    ob = OrderbookSnapshot(
                        exchange="bybit",
                        symbol=d["s"],
                        bids=[OrderbookLevel(price=float(b[0]), quantity=float(b[1])) for b in d.get("b", [])],
                        asks=[OrderbookLevel(price=float(a[0]), quantity=float(a[1])) for a in d.get("a", [])],
                        timestamp=data.get("ts", time.time() * 1000) / 1000,
                    )
                    await self._emit_orderbook(ob)

    # ── WebSocket: Likidasyonlar ──────────────────

    async def _ws_liquidations(self):
        subs = [f"liquidation.{self._normalize_symbol(s)}" for s in self.symbols]
        async with websockets.connect(WS_LINEAR, **self.WS_KWARGS) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": subs}))
            logger.info("[bybit] Likidasyon stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if "liquidation" in data.get("topic", ""):
                    d = data["data"]
                    liq = LiquidationData(
                        exchange="bybit",
                        symbol=d.get("symbol", ""),
                        side=d.get("side", ""),
                        price=float(d.get("price", 0)),
                        quantity=float(d.get("size", 0)),
                        timestamp=float(d.get("updatedTime", time.time() * 1000)) / 1000,
                    )
                    await self._emit_liquidation(liq)

    # ── REST: Open Interest ───────────────────────

    async def _poll_open_interest(self) -> List[OpenInterestData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        url = f"{REST_BASE}/v5/market/open-interest?category=linear&symbol={self._normalize_symbol(sym)}&intervalTime=5min&limit=1"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            rows = data.get("result", {}).get("list", [])
                            if rows:
                                oi = OpenInterestData(
                                    exchange="bybit",
                                    symbol=sym,
                                    value=float(rows[0].get("openInterest", 0)),
                                    timestamp=time.time(),
                                )
                                if hasattr(self, "on_oi") and self.on_oi:
                                    await self.on_oi(oi)
            except Exception as exc:
                logger.error("[bybit] OI poll hatası: %s", exc)
            await asyncio.sleep(10)

    # ── REST: Funding Rate ────────────────────────

    async def _poll_funding_rate(self) -> List[FundingRateData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        url = f"{REST_BASE}/v5/market/tickers?category=linear&symbol={self._normalize_symbol(sym)}"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            rows = data.get("result", {}).get("list", [])
                            if rows:
                                row = rows[0]
                                # fundingRate interval: Bybit V5 döndürüyor (dakika cinsinden)
                                # Bazı coinler 4h, çoğu 8h
                                interval_min = int(row.get("fundingInterval", 480))  # default 480 dk = 8h
                                interval_hours = interval_min // 60

                                fr = FundingRateData(
                                    exchange="bybit",
                                    symbol=sym,
                                    rate=float(row.get("fundingRate", 0)),
                                    next_funding_time=float(row.get("nextFundingTime", 0)) / 1000,
                                    funding_interval_hours=interval_hours,
                                    timestamp=time.time(),
                                )
                                if hasattr(self, "on_funding") and self.on_funding:
                                    await self.on_funding(fr)
            except Exception as exc:
                logger.error("[bybit] FR poll hatası: %s", exc)
            await asyncio.sleep(30)
