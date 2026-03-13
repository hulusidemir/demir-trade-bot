"""
Trade Bot — Coinbase Exchange Adapter
Coinbase Advanced Trade API (Spot & Futures data).
Coinbase'in futures verileri sınırlı olduğundan, ağırlıklı Spot tarafı kullanılır.
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

logger = logging.getLogger("exchange.coinbase")

WS_URL = "wss://advanced-trade-ws.coinbase.com"
REST_BASE = "https://api.coinbase.com"


class CoinbaseExchange(BaseExchange):
    name = "coinbase"

    def _product_id(self, symbol: str) -> str:
        """BTC/USDT → BTC-USDT"""
        return symbol.replace("/", "-")

    # ── WebSocket: Spot Trades ────────────────────

    async def _ws_trades(self):
        product_ids = [self._product_id(s) for s in self.symbols]
        sub_msg = {
            "type": "subscribe",
            "product_ids": product_ids,
            "channel": "market_trades",
        }
        async with websockets.connect(WS_URL, ping_interval=20) as ws:
            await ws.send(json.dumps(sub_msg))
            logger.info("[coinbase] Trade stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("channel") != "market_trades":
                    continue
                for event in data.get("events", []):
                    for t in event.get("trades", []):
                        trade = TradeData(
                            exchange="coinbase",
                            symbol=t.get("product_id", ""),
                            price=float(t.get("price", 0)),
                            quantity=float(t.get("size", 0)),
                            is_buyer_maker=(t.get("side", "") == "SELL"),
                            timestamp=time.time(),
                        )
                        await self._emit_trade(trade)

    # ── WebSocket: Orderbook ──────────────────────

    async def _ws_orderbook(self):
        product_ids = [self._product_id(s) for s in self.symbols]
        sub_msg = {
            "type": "subscribe",
            "product_ids": product_ids,
            "channel": "level2",
        }
        async with websockets.connect(WS_URL, ping_interval=20) as ws:
            await ws.send(json.dumps(sub_msg))
            logger.info("[coinbase] Orderbook stream bağlandı.")
            async for msg in ws:
                data = json.loads(msg)
                if data.get("channel") != "level2":
                    continue
                for event in data.get("events", []):
                    updates = event.get("updates", [])
                    bids = [
                        OrderbookLevel(price=float(u["price_level"]), quantity=float(u["new_quantity"]))
                        for u in updates if u.get("side") == "bid"
                    ]
                    asks = [
                        OrderbookLevel(price=float(u["price_level"]), quantity=float(u["new_quantity"]))
                        for u in updates if u.get("side") == "offer"
                    ]
                    if bids or asks:
                        ob = OrderbookSnapshot(
                            exchange="coinbase",
                            symbol=event.get("product_id", ""),
                            bids=bids,
                            asks=asks,
                            timestamp=time.time(),
                        )
                        await self._emit_orderbook(ob)

    # ── Coinbase: Likidasyon yok (Spot-ağırlıklı) ─

    async def _ws_liquidations(self):
        # Coinbase spot — likidasyon stream'i yok, boş bırakıyoruz
        while self._running:
            await asyncio.sleep(60)

    # ── REST: OI — Coinbase futures sınırlı ───────

    async def _poll_open_interest(self) -> List[OpenInterestData]:
        while self._running:
            await asyncio.sleep(60)

    # ── REST: FR — Yok ────────────────────────────

    async def _poll_funding_rate(self) -> List[FundingRateData]:
        while self._running:
            await asyncio.sleep(60)
