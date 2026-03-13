"""
Trade Bot — Kraken Exchange Adapter
Kraken Futures (Cryptofacilities) & Spot WebSocket.
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

logger = logging.getLogger("exchange.kraken")

WS_SPOT = "wss://ws.kraken.com/v2"
WS_FUTURES = "wss://futures.kraken.com/ws/v1"
REST_BASE = "https://api.kraken.com"
REST_FUTURES = "https://futures.kraken.com"


class KrakenExchange(BaseExchange):
    name = "kraken"

    def _spot_pair(self, symbol: str) -> str:
        """BTC/USDT → BTC/USDT (Kraken v2 formatı)"""
        return symbol

    def _futures_pair(self, symbol: str) -> str:
        """BTC/USDT → PF_XBTUSD (yaklaşık eşleştirme)"""
        mapping = {
            "BTC/USDT": "PF_XBTUSD",
            "ETH/USDT": "PF_ETHUSD",
            "SOL/USDT": "PF_SOLUSD",
            "XRP/USDT": "PF_XRPUSD",
            "DOGE/USDT": "PF_DOGEUSD",
        }
        return mapping.get(symbol, f"PF_{symbol.split('/')[0]}USD")

    # ── WebSocket: Spot Trades ────────────────────

    async def _ws_trades(self):
        pairs = [self._spot_pair(s) for s in self.symbols]
        sub_msg = {
            "method": "subscribe",
            "params": {
                "channel": "trade",
                "symbol": pairs,
            },
        }
        async with websockets.connect(WS_SPOT, **self.WS_KWARGS) as ws:
            await ws.send(json.dumps(sub_msg))
            logger.info("[kraken] Spot trade stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("channel") != "trade":
                    continue
                for t in data.get("data", []):
                    trade = TradeData(
                        exchange="kraken",
                        symbol=t.get("symbol", ""),
                        price=float(t.get("price", 0)),
                        quantity=float(t.get("qty", 0)),
                        is_buyer_maker=(t.get("side", "") == "sell"),
                        timestamp=time.time(),
                    )
                    await self._emit_trade(trade)

    # ── WebSocket: Orderbook (Spot) ───────────────

    async def _ws_orderbook(self):
        pairs = [self._spot_pair(s) for s in self.symbols]
        sub_msg = {
            "method": "subscribe",
            "params": {
                "channel": "book",
                "symbol": pairs,
                "depth": 25,
            },
        }
        async with websockets.connect(WS_SPOT, **self.WS_KWARGS) as ws:
            await ws.send(json.dumps(sub_msg))
            logger.info("[kraken] Orderbook stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("channel") != "book":
                    continue
                for d in data.get("data", []):
                    ob = OrderbookSnapshot(
                        exchange="kraken",
                        symbol=d.get("symbol", ""),
                        bids=[
                            OrderbookLevel(price=float(b["price"]), quantity=float(b["qty"]))
                            for b in d.get("bids", [])
                        ],
                        asks=[
                            OrderbookLevel(price=float(a["price"]), quantity=float(a["qty"]))
                            for a in d.get("asks", [])
                        ],
                        timestamp=time.time(),
                    )
                    await self._emit_orderbook(ob)

    # ── Kraken Futures: Likidasyon ────────────────

    async def _ws_liquidations(self):
        # Kraken Futures public WS — sınırlı likidasyon verisi
        while self._running:
            await asyncio.sleep(60)

    # ── REST: Open Interest (Futures) ─────────────

    async def _poll_open_interest(self) -> List[OpenInterestData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        ticker = self._futures_pair(sym)
                        url = f"{REST_FUTURES}/derivatives/api/v3/tickers"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            for t in data.get("tickers", []):
                                if t.get("symbol") == ticker:
                                    oi = OpenInterestData(
                                        exchange="kraken",
                                        symbol=sym,
                                        value=float(t.get("openInterest", 0)),
                                        timestamp=time.time(),
                                    )
                                    if hasattr(self, "on_oi") and self.on_oi:
                                        await self.on_oi(oi)
            except Exception as exc:
                logger.error("[kraken] OI poll hatası: %s", exc)
            await asyncio.sleep(15)

    # ── REST: Funding Rate ────────────────────────

    async def _poll_funding_rate(self) -> List[FundingRateData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        ticker = self._futures_pair(sym)
                        url = f"{REST_FUTURES}/derivatives/api/v3/tickers"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            for t in data.get("tickers", []):
                                if t.get("symbol") == ticker:
                                    fr = FundingRateData(
                                        exchange="kraken",
                                        symbol=sym,
                                        rate=float(t.get("fundingRate", 0)),
                                        timestamp=time.time(),
                                    )
                                    if hasattr(self, "on_funding") and self.on_funding:
                                        await self.on_funding(fr)
            except Exception as exc:
                logger.error("[kraken] FR poll hatası: %s", exc)
            await asyncio.sleep(30)
