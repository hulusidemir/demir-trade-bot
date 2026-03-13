"""
Trade Bot — OKX Exchange Adapter
OKX V5 WebSocket + REST API.
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

logger = logging.getLogger("exchange.okx")

WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"
REST_BASE = "https://www.okx.com"


class OKXExchange(BaseExchange):
    name = "okx"

    def _inst_id(self, symbol: str, inst_type: str = "SWAP") -> str:
        """BTC/USDT → BTC-USDT-SWAP  veya  BTC-USDT (spot)"""
        base, quote = symbol.split("/")
        if inst_type == "SWAP":
            return f"{base}-{quote}-SWAP"
        return f"{base}-{quote}"

    # ── WebSocket: Futures Trades ─────────────────

    async def _ws_trades(self):
        args = [{"channel": "trades", "instId": self._inst_id(s)} for s in self.symbols]
        async with websockets.connect(WS_PUBLIC, ping_interval=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            logger.info("[okx] Futures trade stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("event"):
                    continue
                for t in data.get("data", []):
                    trade = TradeData(
                        exchange="okx",
                        symbol=t.get("instId", ""),
                        price=float(t["px"]),
                        quantity=float(t["sz"]),
                        is_buyer_maker=(t["side"] == "sell"),
                        timestamp=float(t["ts"]) / 1000,
                    )
                    await self._emit_trade(trade)

    # ── WebSocket: Orderbook ──────────────────────

    async def _ws_orderbook(self):
        args = [{"channel": "books5", "instId": self._inst_id(s)} for s in self.symbols]
        async with websockets.connect(WS_PUBLIC, ping_interval=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            logger.info("[okx] Orderbook stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("event"):
                    continue
                for d in data.get("data", []):
                    ob = OrderbookSnapshot(
                        exchange="okx",
                        symbol=data.get("arg", {}).get("instId", ""),
                        bids=[OrderbookLevel(price=float(b[0]), quantity=float(b[1])) for b in d.get("bids", [])],
                        asks=[OrderbookLevel(price=float(a[0]), quantity=float(a[1])) for a in d.get("asks", [])],
                        timestamp=float(d.get("ts", time.time() * 1000)) / 1000,
                    )
                    await self._emit_orderbook(ob)

    # ── WebSocket: Likidasyonlar ──────────────────

    async def _ws_liquidations(self):
        args = [{"channel": "liquidation-orders", "instType": "SWAP"}]
        async with websockets.connect(WS_PUBLIC, ping_interval=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            logger.info("[okx] Likidasyon stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("event"):
                    continue
                for d in data.get("data", []):
                    for detail in d.get("details", []):
                        liq = LiquidationData(
                            exchange="okx",
                            symbol=d.get("instId", ""),
                            side=detail.get("side", "").upper(),
                            price=float(detail.get("bkPx", 0)),
                            quantity=float(detail.get("sz", 0)),
                            timestamp=float(detail.get("ts", time.time() * 1000)) / 1000,
                        )
                        await self._emit_liquidation(liq)

    # ── REST: Open Interest ───────────────────────

    async def _poll_open_interest(self) -> List[OpenInterestData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        inst = self._inst_id(sym)
                        url = f"{REST_BASE}/api/v5/public/open-interest?instType=SWAP&instId={inst}"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            rows = data.get("data", [])
                            if rows:
                                oi = OpenInterestData(
                                    exchange="okx",
                                    symbol=sym,
                                    value=float(rows[0].get("oi", 0)),
                                    timestamp=time.time(),
                                )
                                if hasattr(self, "on_oi") and self.on_oi:
                                    await self.on_oi(oi)
            except Exception as exc:
                logger.error("[okx] OI poll hatası: %s", exc)
            await asyncio.sleep(10)

    # ── REST: Funding Rate ────────────────────────

    async def _poll_funding_rate(self) -> List[FundingRateData]:
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    for sym in self.symbols:
                        inst = self._inst_id(sym)
                        url = f"{REST_BASE}/api/v5/public/funding-rate?instId={inst}"
                        async with session.get(url) as resp:
                            data = await resp.json()
                            rows = data.get("data", [])
                            if rows:
                                fr = FundingRateData(
                                    exchange="okx",
                                    symbol=sym,
                                    rate=float(rows[0].get("fundingRate", 0)),
                                    next_funding_time=float(rows[0].get("nextFundingTime", 0)) / 1000,
                                    timestamp=time.time(),
                                )
                                if hasattr(self, "on_funding") and self.on_funding:
                                    await self.on_funding(fr)
            except Exception as exc:
                logger.error("[okx] FR poll hatası: %s", exc)
            await asyncio.sleep(30)
