"""
Trade Bot — Bybit Symbol Fetcher
Bybit Linear (USDT Perpetual) borsasındaki TÜM aktif sembolleri çeker.
"""

from __future__ import annotations

import logging
from typing import List

import aiohttp

logger = logging.getLogger("exchanges.symbol_fetcher")

REST_BASE = "https://api.bybit.com"


async def fetch_all_bybit_symbols() -> List[str]:
    """
    Bybit V5 API'den tüm aktif USDT perpetual sembollerini çeker.
    Returns: ["BTC/USDT", "ETH/USDT", "SOL/USDT", …]
    """
    url = f"{REST_BASE}/v5/market/instruments-info"
    params = {
        "category": "linear",
        "limit": "1000",
        "status": "Trading",
    }

    all_symbols: List[str] = []
    cursor = ""

    async with aiohttp.ClientSession() as session:
        while True:
            if cursor:
                params["cursor"] = cursor

            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error("Bybit instruments API %d döndü", resp.status)
                    break

                data = await resp.json()
                result = data.get("result", {})
                instruments = result.get("list", [])

                for inst in instruments:
                    symbol_raw = inst.get("symbol", "")       # BTCUSDT
                    settle_coin = inst.get("settleCoin", "")   # USDT
                    quote_coin = inst.get("quoteCoin", "")     # USDT
                    status = inst.get("status", "")

                    # Sadece USDT settle + aktif olanlar
                    if settle_coin == "USDT" and status == "Trading":
                        # BTCUSDT → BTC/USDT
                        base = symbol_raw.replace(quote_coin, "")
                        unified = f"{base}/{quote_coin}"
                        all_symbols.append(unified)

                # Pagination
                cursor = result.get("nextPageCursor", "")
                if not cursor:
                    break

    # Sırala: BTC ve ETH en başta, sonra alfabetik
    priority = {"BTC/USDT": 0, "ETH/USDT": 1, "SOL/USDT": 2, "XRP/USDT": 3}
    all_symbols.sort(key=lambda s: (priority.get(s, 999), s))

    logger.info(
        "Bybit'ten %d adet USDT perpetual sembol çekildi.", len(all_symbols)
    )
    return all_symbols
