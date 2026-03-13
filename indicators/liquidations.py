"""
Trade Bot — Aggregated Liquidation Level Tracker
Kümülatif likidasyon haritası ve sweep tespiti.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

from core.models import LiquidationData

logger = logging.getLogger("indicator.liquidations")

_MAX_EVENTS = 5_000


class LiquidationTracker:
    """
    Likidasyon Isı Haritası:
    - Likidasyon seviyelerini (fiyat kümeleri) takip eder.
    - "Sweep" tespiti: Bir seviyenin temizlenmesini algılar.
    """

    def __init__(self):
        # {symbol: deque[LiquidationData]}
        self._events: Dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_EVENTS))

        # Likidasyon yoğunluk haritası: {symbol: {price_bucket: total_usd}}
        self._heatmap: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))

        # Bucket boyutu (USDT cinsinden fiyat aralığı)
        self._bucket_sizes: Dict[str, float] = {}

    def _get_bucket_size(self, symbol: str, price: float) -> float:
        """Fiyata göre dinamik bucket boyutu."""
        if symbol not in self._bucket_sizes:
            # ~%0.1'lik dilimler
            self._bucket_sizes[symbol] = max(price * 0.001, 1.0)
        return self._bucket_sizes[symbol]

    def _price_to_bucket(self, symbol: str, price: float) -> int:
        bucket_sz = self._get_bucket_size(symbol, price)
        return int(price / bucket_sz)

    # ── Veri Girişi ───────────────────────────────

    def on_liquidation(self, liq: LiquidationData):
        self._events[liq.symbol].append(liq)
        bucket = self._price_to_bucket(liq.symbol, liq.price)
        self._heatmap[liq.symbol][bucket] += liq.quantity * liq.price

    # ── Hesaplama ─────────────────────────────────

    def get_recent_volume(self, symbol: str, window_sec: float = 60) -> Tuple[float, float]:
        """
        Son penceredeki toplam likidasyon hacmi.
        Returns:
            long_liqs   — Likide edilen long pozisyonlar (USDT)
            short_liqs  — Likide edilen short pozisyonlar (USDT)
        """
        cutoff = time.time() - window_sec
        long_vol = 0.0
        short_vol = 0.0

        for liq in reversed(self._events.get(symbol, deque())):
            if liq.timestamp < cutoff:
                break
            vol = liq.quantity * liq.price
            if liq.side.upper() in ("SELL", "LONG"):  # Long likidasyon
                long_vol += vol
            else:
                short_vol += vol

        return long_vol, short_vol

    def get_hottest_levels(self, symbol: str, top_n: int = 5) -> List[Tuple[float, float]]:
        """
        En yoğun likidasyon seviyeleri.
        Returns: [(price, total_usd), ...] en yoğundan seyreğe sıralı.
        """
        heatmap = self._heatmap.get(symbol, {})
        if not heatmap:
            return []

        bucket_sz = self._get_bucket_size(symbol, 1)  # fallback
        sorted_buckets = sorted(heatmap.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return [(bucket * bucket_sz, vol) for bucket, vol in sorted_buckets]

    def is_sweep_detected(
        self, symbol: str, current_price: float, window_sec: float = 120
    ) -> Tuple[bool, str, float]:
        """
        Likidasyon Sweep tespiti:
        Fiyat bir likidasyon havuzuna girdi ve OI resetlendi.

        Returns:
            swept     — Sweep oldu mu
            direction — 'LONG' (aşağı sweep → dönüş yukarı) veya 'SHORT' (yukarı sweep → dönüş aşağı)
            level     — Sweep edilen seviye
        """
        cutoff = time.time() - window_sec
        long_vol = 0.0
        short_vol = 0.0

        for liq in reversed(self._events.get(symbol, deque())):
            if liq.timestamp < cutoff:
                break
            vol = liq.quantity * liq.price
            if liq.side.upper() in ("SELL", "LONG"):
                long_vol += vol
            else:
                short_vol += vol

        # Anlamlı likidasyon miktarı ($500K+)
        min_sweep_vol = 500_000

        if long_vol > min_sweep_vol and long_vol > short_vol * 3:
            return True, "LONG", current_price  # Long'lar temizlendi, reversal UP beklenir
        elif short_vol > min_sweep_vol and short_vol > long_vol * 3:
            return True, "SHORT", current_price  # Short'lar temizlendi, reversal DOWN beklenir

        return False, "", 0.0

    def get_nearest_pool(self, symbol: str, current_price: float, direction: str = "below") -> Optional[float]:
        """
        Fiyata en yakın likidasyon havuzu.
        TP hedefi veya giriş bölgesi olarak kullanılır.
        """
        hot = self.get_hottest_levels(symbol, top_n=10)
        if not hot:
            return None

        if direction == "below":
            below = [(p, v) for p, v in hot if p < current_price]
            return max(below, key=lambda x: x[1])[0] if below else None
        else:
            above = [(p, v) for p, v in hot if p > current_price]
            return min(above, key=lambda x: x[1])[0] if above else None
