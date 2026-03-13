"""
Trade Bot — SETUP A: A-Kalite Reversal / Sweep
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tetikleme Koşulları (TAMAMI sağlanmalı):
1. Fiyat büyük bir kümülatif likidasyon havuzuna girer
2. OI aniden sıfırlanır/düşer (likidasyon gerçekleşti kanıtı)
3. Taker Buy/Sell oranı yön değiştirir
4. Hacim Deltası geri dönüş yönünde (Reversal) patlama yapar
→ Bu bir DÖNÜŞ işlemidir.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.models import AggregatedState, Direction, SetupType, Signal, SignalType

logger = logging.getLogger("signal.setup_a")


class SetupADetector:
    """Reversal / Sweep sinyal tespiti."""

    def __init__(
        self,
        oi_drop_pct: float = 3.0,
        cvd_spike_pct: float = 50.0,
        taker_flip_threshold: float = 0.15,
        min_confidence: float = 0.75,
    ):
        self.oi_drop_pct = oi_drop_pct
        self.cvd_spike_pct = cvd_spike_pct
        self.taker_flip_threshold = taker_flip_threshold
        self.min_confidence = min_confidence

    def evaluate(self, state: AggregatedState) -> Optional[Signal]:
        """
        AggregatedState'i değerlendir.
        Koşullar sağlanıyorsa Signal döndür, yoksa None.
        """
        score = 0.0
        direction_votes: dict = {"LONG": 0, "SHORT": 0}

        # ── Koşul 1: OI Düşüşü (Likidasyon kanıtı) ──
        if state.oi_change_pct <= -self.oi_drop_pct:
            score += 0.30
            # Büyük OI düşüşü → Likidasyonlar tetiklendi
            # Hangi taraf temizlendi?
            if state.total_long_liqs > state.total_short_liqs * 2:
                direction_votes["LONG"] += 1   # Long'lar temizlendi → Reversal UP
            elif state.total_short_liqs > state.total_long_liqs * 2:
                direction_votes["SHORT"] += 1  # Short'lar temizlendi → Reversal DOWN

        # ── Koşul 2: Taker Ratio Yön Değişimi ──
        prev_bearish = state.taker_ratio_prev < (1.0 - self.taker_flip_threshold)
        now_bullish = state.taker_ratio > (1.0 + self.taker_flip_threshold)
        prev_bullish = state.taker_ratio_prev > (1.0 + self.taker_flip_threshold)
        now_bearish = state.taker_ratio < (1.0 - self.taker_flip_threshold)

        if prev_bearish and now_bullish:
            score += 0.25
            direction_votes["LONG"] += 1
        elif prev_bullish and now_bearish:
            score += 0.25
            direction_votes["SHORT"] += 1

        # ── Koşul 3: CVD Reversal Patlaması ──
        spot_strong = abs(state.spot_cvd_change_pct) >= self.cvd_spike_pct
        fut_strong = abs(state.futures_cvd_change_pct) >= self.cvd_spike_pct

        if spot_strong or fut_strong:
            score += 0.25
            if state.spot_cvd_change_pct > 0 or state.futures_cvd_change_pct > 0:
                direction_votes["LONG"] += 1
            else:
                direction_votes["SHORT"] += 1

        # ── Koşul 4: Likidasyon havuzu sweep kanıtı ──
        total_liqs = state.total_long_liqs + state.total_short_liqs
        if total_liqs > 500_000:  # $500K+ likidasyon
            score += 0.20

        # ── Karar ──
        if score < self.min_confidence:
            return None

        # Yön belirle
        direction = Direction.LONG if direction_votes["LONG"] > direction_votes["SHORT"] else Direction.SHORT

        # Scalp vs Day Trade
        # 1m/5m'de tetiklendiyse → Scalp
        is_scalp = abs(state.price_change_pct_1m) > 0.3 or abs(state.price_change_pct_5m) > 0.8
        sig_type = SignalType.SCALP if is_scalp else SignalType.DAYTRADE

        # Entry / SL / TP hesapla
        entry, sl, tp1, tp2 = self._calc_levels(state, direction)

        signal = Signal(
            symbol=state.symbol,
            setup=SetupType.A_REVERSAL,
            signal_type=sig_type,
            direction=direction,
            confidence=min(score, 1.0),
            entry_low=entry * 0.999,
            entry_high=entry * 1.001,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            bybit_funding_rate=state.bybit_fr,
            bybit_next_funding_ts=state.bybit_next_funding_ts,
            bybit_fr_interval_hours=state.bybit_fr_interval_hours,
            state=state,
        )

        logger.info(
            "🚨 SETUP A TETİKLENDİ: %s %s %s güven=%.0f%%",
            state.symbol, direction.value, sig_type.value, score * 100,
        )

        return signal

    def _calc_levels(
        self, state: AggregatedState, direction: Direction
    ) -> tuple:
        """Entry, SL, TP1, TP2 hesapla."""
        price = state.price

        if direction == Direction.LONG:
            entry = price
            sl = price * 0.995       # %0.5 altı
            tp1 = price * 1.01       # %1 yukarı
            tp2 = price * 1.025      # %2.5 yukarı
        else:
            entry = price
            sl = price * 1.005       # %0.5 üstü
            tp1 = price * 0.99       # %1 aşağı
            tp2 = price * 0.975      # %2.5 aşağı

        return entry, sl, tp1, tp2
