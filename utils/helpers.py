"""
Trade Bot — Utility / Helper Functions
"""

from __future__ import annotations

import time
from typing import Any, Dict


def normalize_symbol(symbol: str) -> str:
    """
    Farklı borsa formatlarını standart formata çevir.
    BTCUSDT, BTC-USDT, BTC/USDT → BTC/USDT
    """
    s = symbol.upper().replace("-SWAP", "").replace("-PERP", "")
    if "/" in s:
        return s
    # BTCUSDT → BTC/USDT
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}"
    return s


def safe_float(value: Any, default: float = 0.0) -> float:
    """Güvenli float dönüşümü."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def timestamp_ms() -> int:
    """Milisaniye cinsinden timestamp."""
    return int(time.time() * 1000)


def truncate(value: float, decimals: int = 2) -> float:
    """Sayıyı belirli ondalık basamağa kırp (yuvarlama olmadan)."""
    factor = 10 ** decimals
    return int(value * factor) / factor


def format_usd(value: float) -> str:
    """$1,234,567.89 formatı."""
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    elif abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K"
    return f"${value:,.2f}"
