"""
Trade Bot — SETUP B: A-Kalite Day Trade Divergence (Tuzak)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tetikleme Koşulları:
- Fiyat düşerken/yatayken:
  • Aggregated OI artıyor (pozisyon açılıyor)
  • Futures CVD düşüyor (short açılıyor)
  • Spot CVD yatay/yükselişte (Spot alıcısı mal topluyor)
  → LONG yönlü tetiklenir (Short Squeeze / Trap).

- Tersi durumda SHORT tetiklenir.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.models import AggregatedState, Direction, SetupType, Signal, SignalType

logger = logging.getLogger("signal.setup_b")


class SetupBDetector:
    """Divergence / Trap sinyal tespiti."""

    def __init__(
        self,
        oi_rise_pct: float = 2.0,
        cvd_divergence_min: float = 30.0,
        min_confidence: float = 0.75,
    ):
        self.oi_rise_pct = oi_rise_pct
        self.cvd_divergence_min = cvd_divergence_min
        self.min_confidence = min_confidence

    def evaluate(self, state: AggregatedState) -> Optional[Signal]:
        score = 0.0
        direction = None

        # ── LONG SETUP: Short Squeeze / Trap ──
        long_score = self._eval_long_trap(state)
        short_score = self._eval_short_trap(state)

        if long_score > short_score and long_score >= self.min_confidence:
            score = long_score
            direction = Direction.LONG
        elif short_score > long_score and short_score >= self.min_confidence:
            score = short_score
            direction = Direction.SHORT
        else:
            return None

        # Her zaman Day Trade (divergence = orta vadeli setup)
        sig_type = SignalType.DAYTRADE

        entry, sl, tp1, tp2 = self._calc_levels(state, direction)

        signal = Signal(
            symbol=state.symbol,
            setup=SetupType.B_DIVERGENCE,
            signal_type=sig_type,
            direction=direction,
            confidence=min(score, 1.0),
            entry_low=entry * 0.998,
            entry_high=entry * 1.002,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            bybit_funding_rate=state.bybit_fr,
            bybit_next_funding_ts=state.bybit_next_funding_ts,
            bybit_fr_interval_hours=state.bybit_fr_interval_hours,
            state=state,
        )

        logger.info(
            "🚨 SETUP B TETİKLENDİ: %s %s güven=%.0f%%",
            state.symbol, direction.value, score * 100,
        )

        return signal

    def _eval_long_trap(self, state: AggregatedState) -> float:
        """
        Short Squeeze / Trap değerlendirmesi.
        Fiyat düşerken/yatay + OI artıyor + Futures CVD düşüyor + Spot CVD yükseliyor.
        """
        score = 0.0

        # Fiyat yatay veya düşüşte
        if state.price_change_pct_15m <= 0.5:
            score += 0.15

        # OI artıyor (yeni pozisyon açılıyor)
        if state.oi_change_pct >= self.oi_rise_pct:
            score += 0.25

        # Futures CVD negatif/düşüşte (short açılıyor)
        if state.futures_cvd < 0 or state.futures_cvd_change_pct < -self.cvd_divergence_min:
            score += 0.25

        # Spot CVD yatay veya yükselişte (akıllı para topluyor)
        if state.spot_cvd >= 0 or state.spot_cvd_change_pct > 0:
            score += 0.20

        # FR negatif (short kalabalık → squeeze riski)
        if state.bybit_fr < -0.005:
            score += 0.15

        return score

    def _eval_short_trap(self, state: AggregatedState) -> float:
        """
        Long Squeeze / Trap değerlendirmesi.
        Fiyat yükselirken/yatay + OI artıyor + Futures CVD yükseliyor + Spot CVD düşüyor.
        """
        score = 0.0

        # Fiyat yatay veya yükselişte
        if state.price_change_pct_15m >= -0.5:
            score += 0.15

        # OI artıyor
        if state.oi_change_pct >= self.oi_rise_pct:
            score += 0.25

        # Futures CVD pozitif/yükselişte (long açılıyor)
        if state.futures_cvd > 0 or state.futures_cvd_change_pct > self.cvd_divergence_min:
            score += 0.25

        # Spot CVD yatay veya düşüşte (akıllı para satıyor)
        if state.spot_cvd <= 0 or state.spot_cvd_change_pct < 0:
            score += 0.20

        # FR pozitif (long kalabalık → squeeze riski)
        if state.bybit_fr > 0.005:
            score += 0.15

        return score

    def _calc_levels(
        self, state: AggregatedState, direction: Direction
    ) -> tuple:
        price = state.price

        if direction == Direction.LONG:
            entry = price
            sl = price * 0.992       # %0.8 altı (daha geniş — day trade)
            tp1 = price * 1.015      # %1.5 yukarı
            tp2 = price * 1.035      # %3.5 yukarı
        else:
            entry = price
            sl = price * 1.008
            tp1 = price * 0.985
            tp2 = price * 0.965

        return entry, sl, tp1, tp2
