"""
Trade Bot — Whale Aggression Detector
Profesyonel seviye balina tespiti:
- Minimum USD hacim eşiği (küçük işlemleri filtreler)
- 5 saniyelik kümeleme penceresi (cluster detection)
- Yeterli istatistiksel veri gereksinimi (min 30 bucket)
- Standart sapmanın 4x+ aşılması
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple

from core.models import TradeData, WhaleEvent

logger = logging.getLogger("indicator.whale")

_WINDOW = 300   # 5 dakikalık istatistik penceresi
_MAX_TICKS = 20_000
_CLUSTER_SEC = 5  # 5 saniyelik kümeleme penceresi

# Coin bazlı minimum USD eşikleri
_MIN_VOLUME_USD: Dict[str, float] = {
    "BTCUSDT": 100_000,
    "BTC-USDT-SWAP": 100_000,
    "BTC-USDT": 100_000,
    "ETHUSDT": 50_000,
    "ETH-USDT-SWAP": 50_000,
    "ETH-USDT": 50_000,
}
_MIN_VOLUME_DEFAULT = 20_000  # Diğer tüm coinler için $20K


class WhaleDetector:
    """
    Exchange-Specific Whale Aggression:
    Tek bir borsada saniyeler içinde toplam hacmin
    standart sapmasını 4x aşan taker alımı/satımı.

    Filtreler:
    - Minimum USD hacim eşiği (BTC $100K, ETH $50K, diğer $20K)
    - 5 saniyelik kümeleme penceresi
    - Min 30 istatistik bucket (istatistiksel güvenilirlik)
    """

    def __init__(self, std_multiplier: float = 4.0, min_volume_usd: float = 0):
        self.std_multiplier = std_multiplier
        self._min_volume_override = min_volume_usd  # 0 = coin bazlı otomatik
        # {(symbol, exchange): deque[(timestamp, volume_usd, is_buy)]}
        self._ticks: Dict[Tuple[str, str], deque] = defaultdict(
            lambda: deque(maxlen=_MAX_TICKS)
        )
        # Son tespit edilen whale eventler
        self._recent_events: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )

    def _get_min_volume(self, symbol: str) -> float:
        """Coin bazlı minimum USD hacim eşiği."""
        if self._min_volume_override > 0:
            return self._min_volume_override
        return _MIN_VOLUME_USD.get(symbol, _MIN_VOLUME_DEFAULT)

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

        # Son 5 saniyedeki toplam hacmi hesapla (kümeleme)
        now = trade.timestamp
        recent_vol = 0.0
        recent_buy_vol = 0.0
        recent_sell_vol = 0.0
        for ts, v, buy in reversed(self._ticks[key]):
            if now - ts > _CLUSTER_SEC:
                break
            recent_vol += v
            if buy:
                recent_buy_vol += v
            else:
                recent_sell_vol += v

        # Minimum USD hacim filtresi
        min_vol = self._get_min_volume(trade.symbol)
        if recent_vol < min_vol:
            return None

        # Standart sapma hesapla (son 5 dk'lık 5-saniyelik dilimler)
        mean, std = self._calc_stats(key, now)

        if std > 0 and recent_vol > mean + (std * self.std_multiplier):
            # Baskın yönü belirle
            side = "BUY" if recent_buy_vol > recent_sell_vol else "SELL"

            event = WhaleEvent(
                exchange=trade.exchange,
                symbol=trade.symbol,
                side=side,
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
        5-saniyelik dilimlerle mean ve std hesapla.
        """
        window_start = now - _WINDOW
        buckets: Dict[int, float] = defaultdict(float)

        for ts, v, _ in self._ticks[key]:
            if ts < window_start:
                continue
            bucket = int(ts / _CLUSTER_SEC)
            buckets[bucket] += v

        if len(buckets) < 30:
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
