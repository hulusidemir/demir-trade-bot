"""
Trade Bot — Aggregated Orderbook Depth + Spoofing Filter
Kümülatif emir defteri derinliği hesaplar, sahte emirleri filtreler.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.models import OrderbookLevel, OrderbookSnapshot

logger = logging.getLogger("indicator.orderbook")


@dataclass
class TrackedOrder:
    """Spoofing tespiti için takip edilen büyük emir."""
    price: float
    quantity: float
    first_seen: float
    last_seen: float
    side: str  # "bid" veya "ask"


class OrderbookAnalyzer:
    """
    Kümülatif orderbook derinliği ve spoofing filtresi.

    Spoofing Kuralı:
    - Fiyata %1'den uzak
    - 5 saniyeden kısa yaşayan
    - Devasa hacimli (top %5 quantile üzeri)
    → Bu emirler hesaplamaya dahil edilmez.
    """

    def __init__(self, spoof_price_pct: float = 1.0, spoof_ttl_sec: float = 5.0):
        self.spoof_price_pct = spoof_price_pct
        self.spoof_ttl_sec = spoof_ttl_sec

        # { symbol: { exchange: OrderbookSnapshot } }
        self._snapshots: Dict[str, Dict[str, OrderbookSnapshot]] = defaultdict(dict)

        # Spoofing takibi: { (symbol, exchange, price): TrackedOrder }
        self._tracked: Dict[tuple, TrackedOrder] = {}

        # Son temizlik zamanı
        self._last_cleanup = time.time()

    # ── Veri Girişi ───────────────────────────────

    def update(self, ob: OrderbookSnapshot, current_price: float):
        """Yeni bir orderbook snapshot'ı işle."""
        self._snapshots[ob.symbol][ob.exchange] = ob
        self._track_spoofing(ob, current_price)

        # Periyodik temizlik
        now = time.time()
        if now - self._last_cleanup > 10:
            self._cleanup_tracked()
            self._last_cleanup = now

    def _track_spoofing(self, ob: OrderbookSnapshot, current_price: float):
        """Büyük emirleri takip et, kaybolanları spoof olarak işaretle."""
        now = time.time()

        # Mevcut büyük emirleri bul
        seen_keys = set()

        for level in ob.bids:
            key = (ob.symbol, ob.exchange, level.price)
            seen_keys.add(key)

            dist_pct = abs(level.price - current_price) / current_price * 100

            if key in self._tracked:
                self._tracked[key].last_seen = now
                self._tracked[key].quantity = level.quantity
            elif dist_pct > self.spoof_price_pct and level.quantity * current_price > 100_000:
                # Fiyata uzak, büyük emir — takibe al
                self._tracked[key] = TrackedOrder(
                    price=level.price,
                    quantity=level.quantity,
                    first_seen=now,
                    last_seen=now,
                    side="bid",
                )

        for level in ob.asks:
            key = (ob.symbol, ob.exchange, level.price)
            seen_keys.add(key)

            dist_pct = abs(level.price - current_price) / current_price * 100

            if key in self._tracked:
                self._tracked[key].last_seen = now
                self._tracked[key].quantity = level.quantity
            elif dist_pct > self.spoof_price_pct and level.quantity * current_price > 100_000:
                self._tracked[key] = TrackedOrder(
                    price=level.price,
                    quantity=level.quantity,
                    first_seen=now,
                    last_seen=now,
                    side="ask",
                )

    def _cleanup_tracked(self):
        """Kaybolan emirleri kontrol et, spoof olanları kaldır."""
        now = time.time()
        to_remove = []
        for key, order in self._tracked.items():
            lifetime = order.last_seen - order.first_seen
            gone = now - order.last_seen

            if gone > 2:  # 2 saniyedir gözükmeyen
                if lifetime < self.spoof_ttl_sec:
                    logger.debug(
                        "SPOOF TESPİT: %s @%.2f qty=%.4f yaşam=%.1fs",
                        key, order.price, order.quantity, lifetime,
                    )
                to_remove.append(key)
            elif now - order.first_seen > 60:
                # 60 saniyeden uzun yaşayan → değil spoof, temizle
                to_remove.append(key)

        for k in to_remove:
            del self._tracked[k]

    # ── Hesaplama ─────────────────────────────────

    def _is_spoof(self, symbol: str, exchange: str, price: float) -> bool:
        """Verilen fiyattaki emir spoof olarak işaretlenmiş mi?"""
        key = (symbol, exchange, price)
        if key in self._tracked:
            t = self._tracked[key]
            return (t.last_seen - t.first_seen) < self.spoof_ttl_sec
        return False

    def get_aggregated_depth(self, symbol: str, current_price: float) -> Tuple[float, float, float]:
        """
        Spoof filtreli kümülatif derinlik.
        Returns:
            total_bid_depth  — Toplam bid derinliği (USDT)
            total_ask_depth  — Toplam ask derinliği (USDT)
            imbalance        — (bid - ask) / (bid + ask)  [-1, +1]
        """
        total_bid = 0.0
        total_ask = 0.0

        exchange_obs = self._snapshots.get(symbol, {})
        for exchange, ob in exchange_obs.items():
            for level in ob.bids:
                if not self._is_spoof(symbol, exchange, level.price):
                    dist_pct = abs(level.price - current_price) / current_price * 100
                    if dist_pct <= 2.0:  # Fiyata %2 mesafe içindekiler
                        total_bid += level.quantity * level.price

            for level in ob.asks:
                if not self._is_spoof(symbol, exchange, level.price):
                    dist_pct = abs(level.price - current_price) / current_price * 100
                    if dist_pct <= 2.0:
                        total_ask += level.quantity * level.price

        denom = total_bid + total_ask
        imbalance = (total_bid - total_ask) / denom if denom > 0 else 0.0

        return total_bid, total_ask, imbalance

    def get_nearest_wall(self, symbol: str, current_price: float, side: str = "ask") -> Optional[float]:
        """
        Fiyata en yakın kalın duvarı bul (TP hedefi olarak).
        """
        exchange_obs = self._snapshots.get(symbol, {})
        best_wall_price = None
        best_wall_qty = 0.0

        for exchange, ob in exchange_obs.items():
            levels = ob.asks if side == "ask" else ob.bids
            for level in levels:
                if self._is_spoof(symbol, exchange, level.price):
                    continue
                value = level.quantity * level.price
                if value > 500_000:  # $500K+ duvar
                    if best_wall_price is None:
                        best_wall_price = level.price
                        best_wall_qty = value
                    else:
                        if side == "ask" and level.price < best_wall_price:
                            best_wall_price = level.price
                            best_wall_qty = value
                        elif side == "bid" and level.price > best_wall_price:
                            best_wall_price = level.price
                            best_wall_qty = value

        return best_wall_price
