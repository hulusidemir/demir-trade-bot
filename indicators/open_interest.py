"""
Trade Bot — Aggregated Open Interest Tracker
Tüm borsaların OI verilerini toplar, değişim oranını hesaplar.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

from core.models import OpenInterestData

logger = logging.getLogger("indicator.oi")

# Her borsa/sembol çifti için son N OI kaydı (zaman serisi)
_MAX_HISTORY = 360  # ~1 saat (10sn aralık × 360)


class OpenInterestTracker:
    """Kümülatif Open Interest takibi."""

    def __init__(self):
        # {symbol: {exchange: deque[(timestamp, value)]}}
        self._data: Dict[str, Dict[str, deque]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=_MAX_HISTORY)))

    # ── Veri Girişi ───────────────────────────────

    def update(self, oi: OpenInterestData):
        self._data[oi.symbol][oi.exchange].append((oi.timestamp, oi.value))

    # ── Hesaplama ─────────────────────────────────

    def get_aggregated(self, symbol: str) -> Tuple[float, float, Dict[str, float]]:
        """
        Returns:
            total_oi       — Tüm borsaların toplam OI'ı.
            oi_change_pct  — Son 1 dakikadaki OI değişim yüzdesi.
            oi_by_exchange — Borsa bazlı güncel OI.
        """
        exchanges = self._data.get(symbol, {})
        total_now = 0.0
        total_prev = 0.0
        by_exchange: Dict[str, float] = {}

        cutoff = time.time() - 60  # 1 dakika önce

        for exch, series in exchanges.items():
            if not series:
                continue
            current = series[-1][1]
            total_now += current
            by_exchange[exch] = current

            # 1 dk önceki en yakın değeri bul
            prev_val = current
            for ts, val in reversed(series):
                if ts <= cutoff:
                    prev_val = val
                    break
            total_prev += prev_val

        change_pct = 0.0
        if total_prev > 0:
            change_pct = ((total_now - total_prev) / total_prev) * 100

        return total_now, change_pct, by_exchange

    def get_oi_drop_detected(self, symbol: str, threshold_pct: float = 3.0) -> bool:
        """OI'ın aniden düştüğünü tespit et (likidasyon kanıtı)."""
        _, change, _ = self.get_aggregated(symbol)
        return change <= -threshold_pct

    def get_oi_rise_detected(self, symbol: str, threshold_pct: float = 3.0) -> bool:
        """OI'ın aniden yükseldiğini tespit et."""
        _, change, _ = self.get_aggregated(symbol)
        return change >= threshold_pct
