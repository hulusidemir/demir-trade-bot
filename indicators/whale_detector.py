"""
Trade Bot — Whale Aggression Detector
Belirli bir borsada toplam hacmin standart sapmasını 3x aşan
taker alım/satım tespiti.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

from core.models import TradeData, WhaleEvent

logger = logging.getLogger("indicator.whale")

_WINDOW = 300   # 5 dakikalık pencere
_MAX_TICKS = 20_000


class WhaleDetector:
    """
    Exchange-Specific Whale Aggression:
    Tek bir borsada saniyeler içinde toplam hacmin
    standart sapmasını 3x aşan taker alımı/satımı.
    """

    def __init__(self, std_multiplier: float = 3.0):
        self.std_multiplier = std_multiplier
        # {(symbol, exchange): deque[(timestamp, volume_usd, is_buy)]}
        self._ticks: Dict[Tuple[str, str], deque] = defaultdict(
            lambda: deque(maxlen=_MAX_TICKS)
        )
        # Son tespit edilen whale eventler
        self._recent_events: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )

    # ── Veri Girişi ───────────────────────────────

    def on_trade(self, trade: TradeData) -> Optional[WhaleEvent]:
        """
        Her trade'i işle, whale agresyonu tespiti yap.
        Returns: WhaleEvent eğer tespit edildiyse, None değilse.
        """
        vol_usd = trade.quantity * trade.price
        is_buy = not trade.is_buyer_maker
        key = (trade.symbol, trade.exchange)

        self._ticks[key].append((trade.timestamp, vol_usd, is_buy))

        # Son 1 saniyedeki toplam hacmi hesapla
        now = trade.timestamp
        recent_vol = 0.0
        for ts, v, _ in reversed(self._ticks[key]):
            if now - ts > 1.0:
                break
            recent_vol += v

        # Standart sapma hesapla (son 5 dk'lık 1-saniyelik dilimler)
        mean, std = self._calc_stats(key, now)

        if std > 0 and recent_vol > mean + (std * self.std_multiplier):
            event = WhaleEvent(
                exchange=trade.exchange,
                symbol=trade.symbol,
                side="BUY" if is_buy else "SELL",
                volume=recent_vol,
                std_multiplier=recent_vol / std if std > 0 else 0,
                timestamp=now,
            )
            self._recent_events[trade.symbol].append(event)
            logger.warning(
                "🐋 WHALE TESPİT: %s %s %s $%.0f (%.1fσ)",
                trade.exchange, trade.symbol, event.side, recent_vol, event.std_multiplier,
            )
            return event

        return None

    def _calc_stats(self, key: Tuple[str, str], now: float) -> Tuple[float, float]:
        """
        1-saniyelik dilimlerle mean ve std hesapla.
        """
        window_start = now - _WINDOW
        buckets: Dict[int, float] = defaultdict(float)

        for ts, v, _ in self._ticks[key]:
            if ts < window_start:
                continue
            bucket = int(ts)
            buckets[bucket] += v

        if len(buckets) < 10:
            return 0.0, 0.0

        values = list(buckets.values())
        n = len(values)
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance)

        return mean, std

    # ── Sorgulama ─────────────────────────────────

    def get_recent_whale_events(self, symbol: str, window_sec: float = 120) -> List[WhaleEvent]:
        """Son penceredeki whale eventleri."""
        cutoff = time.time() - window_sec
        return [
            e for e in self._recent_events.get(symbol, deque())
            if e.timestamp >= cutoff
        ]

    def has_whale_aggression(self, symbol: str, window_sec: float = 60) -> Tuple[bool, Optional[WhaleEvent]]:
        """
        Son pencerede whale agresyonu var mı?
        Returns: (detected, latest_event)
        """
        events = self.get_recent_whale_events(symbol, window_sec)
        if events:
            return True, events[-1]
        return False, None
