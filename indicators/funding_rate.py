"""
Trade Bot — Funding Rate Analyzer
Aggregated FR + Bybit FR çıktısı + FR Arbitraj tespiti.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Dict, Tuple

from core.models import FundingRateData

logger = logging.getLogger("indicator.funding_rate")

_MAX_HISTORY = 120  # ~1 saat (30sn aralık × 120)


class FundingRateAnalyzer:
    """
    Funding Rate analizi:
    - Aggregated FR (tüm borsaların ortalaması)
    - Bybit FR (zorunlu çıktı) + sonraki fonlamaya kalan süre + interval
    - FR Arbitraj Uçurumu (max-min fark)
    """

    def __init__(self, arb_threshold: float = 0.02):
        # {symbol: {exchange: deque[(timestamp, rate)]}}
        self._data: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=_MAX_HISTORY))
        )
        # Bybit ekstra bilgiler: {symbol: (next_funding_ts, interval_hours)}
        self._bybit_meta: Dict[str, tuple] = {}
        self.arb_threshold = arb_threshold  # %0.02

    # ── Veri Girişi ───────────────────────────────

    def update(self, fr: FundingRateData):
        self._data[fr.symbol][fr.exchange].append((fr.timestamp, fr.rate))
        # Bybit meta bilgilerini sakla
        if fr.exchange == "bybit":
            self._bybit_meta[fr.symbol] = (
                fr.next_funding_time,
                fr.funding_interval_hours,
            )

    # ── Hesaplama ─────────────────────────────────

    def get_rates(self, symbol: str) -> Tuple[float, float, float, Dict[str, float]]:
        """
        Returns:
            aggregated_fr  — Tüm borsaların ortalama FR'ı
            bybit_fr       — Bybit'in güncel FR'ı (zorunlu çıktı)
            arb_spread     — Max FR - Min FR (borsalar arası)
            by_exchange    — Borsa bazlı FR
        """
        exchanges = self._data.get(symbol, {})
        rates: Dict[str, float] = {}

        for exch, series in exchanges.items():
            if series:
                rates[exch] = series[-1][1]

        if not rates:
            return 0.0, 0.0, 0.0, {}

        aggregated = sum(rates.values()) / len(rates)
        bybit_fr = rates.get("bybit", aggregated)

        all_rates = list(rates.values())
        arb_spread = max(all_rates) - min(all_rates)

        return aggregated, bybit_fr, arb_spread, rates

    def get_bybit_meta(self, symbol: str) -> Tuple[float, int]:
        """
        Bybit FR meta bilgisi.
        Returns:
            next_funding_ts     — Bir sonraki fonlama zamanı (unix timestamp)
            interval_hours      — Fonlama intervali (saat): 4, 8 veya başka
        """
        return self._bybit_meta.get(symbol, (0.0, 8))

    def is_arb_anomaly(self, symbol: str) -> Tuple[bool, str]:
        """
        FR Arbitraj Uçurumu tespiti.
        Returns:
            anomaly    — Anormal fark var mı
            detail     — Detay mesajı
        """
        _, _, spread, by_exchange = self.get_rates(symbol)

        if spread >= self.arb_threshold and len(by_exchange) >= 2:
            max_ex = max(by_exchange, key=by_exchange.get)
            min_ex = min(by_exchange, key=by_exchange.get)
            detail = (
                f"FR Arbitraj: {max_ex} ({by_exchange[max_ex]:+.4%}) vs "
                f"{min_ex} ({by_exchange[min_ex]:+.4%}) → Fark: {spread:.4%}"
            )
            return True, detail

        return False, ""

    def get_squeeze_potential(self, symbol: str) -> Tuple[bool, str]:
        """
        Funding Rate'e göre squeeze potansiyeli.
        FR çok negatif → Short Squeeze potansiyeli (LONG).
        FR çok pozitif → Long Squeeze potansiyeli (SHORT).
        """
        _, bybit_fr, _, _ = self.get_rates(symbol)

        if bybit_fr <= -0.01:  # %−0.01 ve altı
            return True, "LONG"
        elif bybit_fr >= 0.01:  # %+0.01 ve üstü
            return True, "SHORT"

        return False, ""
