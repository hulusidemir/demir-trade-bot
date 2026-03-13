"""
Trade Bot — Cumulative Volume Delta (CVD) Calculator
Spot ve Futures CVD'yi ayrı ayrı hesaplar.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

from core.models import TradeData

logger = logging.getLogger("indicator.cvd")

_MAX_TICKS = 50_000  # Bellekte tutulacak max tick


class CVDCalculator:
    """
    Kümülatif Hacim Deltası.
    CVD = Σ(Taker Buy Volume - Taker Sell Volume)
    """

    def __init__(self):
        # {symbol: deque[(timestamp, delta)]}  — delta = +qty (buy) veya -qty (sell)
        self._spot: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_TICKS))
        self._futures: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_TICKS))

    # ── Veri Girişi ───────────────────────────────

    def on_trade(self, trade: TradeData):
        """Bir trade geldiğinde CVD'ye ekle."""
        delta = -trade.quantity if trade.is_buyer_maker else trade.quantity
        delta_usd = delta * trade.price

        exchange = trade.exchange.lower()

        # Spot mu Futures mu?
        if "spot" in exchange or exchange in ("coinbase", "kraken"):
            self._spot[trade.symbol].append((trade.timestamp, delta_usd))
        else:
            self._futures[trade.symbol].append((trade.timestamp, delta_usd))

    # ── CVD Hesaplama ─────────────────────────────

    def _cvd_in_window(self, series: deque, window_sec: float) -> float:
        """Belirli bir zaman penceresi içindeki kümülatif delta."""
        cutoff = time.time() - window_sec
        total = 0.0
        for ts, d in reversed(series):
            if ts < cutoff:
                break
            total += d
        return total

    def get_spot_cvd(self, symbol: str, window_sec: float = 60) -> float:
        return self._cvd_in_window(self._spot.get(symbol, deque()), window_sec)

    def get_futures_cvd(self, symbol: str, window_sec: float = 60) -> float:
        return self._cvd_in_window(self._futures.get(symbol, deque()), window_sec)

    def get_cvd_change_pct(self, symbol: str, window_sec: float = 60) -> Tuple[float, float]:
        """
        CVD'nin değişim yüzdesi (önceki periyoda göre).
        Returns: (spot_change_pct, futures_change_pct)
        """
        spot_now = self.get_spot_cvd(symbol, window_sec)
        spot_prev = self.get_spot_cvd(symbol, window_sec * 2) - spot_now

        fut_now = self.get_futures_cvd(symbol, window_sec)
        fut_prev = self.get_futures_cvd(symbol, window_sec * 2) - fut_now

        def safe_pct(now, prev):
            if abs(prev) < 1:
                return 0.0 if abs(now) < 1 else 100.0
            return ((now - prev) / abs(prev)) * 100

        return safe_pct(spot_now, spot_prev), safe_pct(fut_now, fut_prev)

    def is_cvd_spike(self, symbol: str, threshold_pct: float = 50.0, window_sec: float = 60) -> Tuple[bool, str]:
        """
        CVD patlama tespiti.
        Returns: (spike_detected, direction: 'LONG' | 'SHORT' | '')
        """
        spot_chg, fut_chg = self.get_cvd_change_pct(symbol, window_sec)
        combined = (spot_chg + fut_chg) / 2

        if combined >= threshold_pct:
            return True, "LONG"
        elif combined <= -threshold_pct:
            return True, "SHORT"
        return False, ""

    def is_divergence(self, symbol: str, window_sec: float = 300) -> Tuple[bool, str]:
        """
        Setup B: Futures CVD vs Spot CVD divergence.
        Spot alıyor ama Futures satıyor → LONG sinyal.
        Spot satıyor ama Futures alıyor → SHORT sinyal.
        """
        spot = self.get_spot_cvd(symbol, window_sec)
        futures = self.get_futures_cvd(symbol, window_sec)

        # Spot pozitif, Futures negatif → Short Squeeze potansiyeli → LONG
        if spot > 0 and futures < 0 and abs(spot) > abs(futures) * 0.5:
            return True, "LONG"

        # Spot negatif, Futures pozitif → Long Squeeze potansiyeli → SHORT
        if spot < 0 and futures > 0 and abs(spot) > abs(futures) * 0.5:
            return True, "SHORT"

        return False, ""
