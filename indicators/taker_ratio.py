"""
Trade Bot — Taker Buy/Sell Ratio Tracker
Agresif market emirlerinin (taker) oranını hesaplar.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

from core.models import TradeData

logger = logging.getLogger("indicator.taker_ratio")

_MAX_TICKS = 30_000


class TakerRatioTracker:
    """
    Taker Buy / Sell Ratio.
    ratio > 1.0 → Alıcılar agresif
    ratio < 1.0 → Satıcılar agresif
    """

    def __init__(self):
        # {symbol: deque[(timestamp, buy_vol_usd, sell_vol_usd)]}
        self._data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_TICKS))
        self._prev_ratios: Dict[str, float] = defaultdict(lambda: 1.0)

    # ── Veri Girişi ───────────────────────────────

    def on_trade(self, trade: TradeData):
        vol_usd = trade.quantity * trade.price
        if trade.is_buyer_maker:
            # Seller taker (satıcı agresif)
            self._data[trade.symbol].append((trade.timestamp, 0.0, vol_usd))
        else:
            # Buyer taker (alıcı agresif)
            self._data[trade.symbol].append((trade.timestamp, vol_usd, 0.0))

    # ── Hesaplama ─────────────────────────────────

    def get_ratio(self, symbol: str, window_sec: float = 60) -> Tuple[float, float, float]:
        """
        Returns:
            ratio       — buy_vol / sell_vol
            buy_volume  — Toplam taker buy hacmi (USDT)
            sell_volume — Toplam taker sell hacmi (USDT)
        """
        cutoff = time.time() - window_sec
        buy_vol = 0.0
        sell_vol = 0.0

        for ts, bv, sv in reversed(self._data.get(symbol, deque())):
            if ts < cutoff:
                break
            buy_vol += bv
            sell_vol += sv

        ratio = buy_vol / sell_vol if sell_vol > 0 else (2.0 if buy_vol > 0 else 1.0)
        return ratio, buy_vol, sell_vol

    def has_flipped(self, symbol: str, threshold: float = 0.15, window_sec: float = 60) -> Tuple[bool, str]:
        """
        Taker ratio'nun yön değiştirip değiştirmediğini kontrol et.
        Returns:
            flipped   — Yön değişimi oldu mu
            direction — 'LONG' (satıcıdan alıcıya) veya 'SHORT' (alıcıdan satıcıya)
        """
        ratio, _, _ = self.get_ratio(symbol, window_sec)
        prev = self._prev_ratios[symbol]

        flipped = False
        direction = ""

        if prev < (1.0 - threshold) and ratio > (1.0 + threshold):
            flipped = True
            direction = "LONG"
        elif prev > (1.0 + threshold) and ratio < (1.0 - threshold):
            flipped = True
            direction = "SHORT"

        # Önceki oranı güncelle
        self._prev_ratios[symbol] = ratio

        return flipped, direction
