"""
Trade Bot — SETUP C: Borsa Agresyonu / Momentum
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tetikleme Koşulları:
- Spot ve Vadeli CVD aynı anda %50+ artış
- Belirli bir borsada anormal Whale Market Execution tespiti
→ Momentum yönüne scalp.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.models import AggregatedState, Direction, SetupType, Signal, SignalType

logger = logging.getLogger("signal.setup_c")


class SetupCDetector:
    """Momentum / Whale Aggression sinyal tespiti."""

    def __init__(
        self,
        cvd_spike_pct: float = 50.0,
        min_confidence: float = 0.75,
    ):
        self.cvd_spike_pct = cvd_spike_pct
        self.min_confidence = min_confidence

    def evaluate(self, state: AggregatedState) -> Optional[Signal]:
        score = 0.0
        direction = None

        # ── Koşul 1: CVD Momentum (Spot + Futures aynı yönde) ──
        spot_bullish = state.spot_cvd_change_pct >= self.cvd_spike_pct
        fut_bullish = state.futures_cvd_change_pct >= self.cvd_spike_pct
        spot_bearish = state.spot_cvd_change_pct <= -self.cvd_spike_pct
        fut_bearish = state.futures_cvd_change_pct <= -self.cvd_spike_pct

        if spot_bullish and fut_bullish:
            score += 0.40
            direction = Direction.LONG
        elif spot_bearish and fut_bearish:
            score += 0.40
            direction = Direction.SHORT
        else:
            # CVD uyumsuz → setup tetiklenmez
            return None

        # ── Koşul 2: Whale Aggression ──
        if state.whale_events:
            latest_whale = state.whale_events[-1]
            whale_direction = Direction.LONG if latest_whale.side == "BUY" else Direction.SHORT

            if whale_direction == direction:
                score += 0.35
                # Agresyon şiddetine göre bonus
                if latest_whale.std_multiplier >= 5.0:
                    score += 0.10  # Aşırı agresyon bonusu

        # ── Koşul 3: Orderbook İmbalance desteği ──
        if direction == Direction.LONG and state.bid_ask_imbalance > 0.15:
            score += 0.15
        elif direction == Direction.SHORT and state.bid_ask_imbalance < -0.15:
            score += 0.15

        if score < self.min_confidence:
            return None

        # Her zaman Scalp (momentum = kısa vadeli)
        sig_type = SignalType.SCALP

        entry, sl, tp1, tp2 = self._calc_levels(state, direction)

        whale_note = ""
        if state.whale_events:
            w = state.whale_events[-1]
            whale_note = f"{w.exchange.upper()} bu coine saldırıyor! ${w.volume:,.0f} taker {w.side} ({w.std_multiplier:.1f}σ)"

        signal = Signal(
            symbol=state.symbol,
            setup=SetupType.C_MOMENTUM,
            signal_type=sig_type,
            direction=direction,
            confidence=min(score, 1.0),
            entry_low=entry * 0.9995,
            entry_high=entry * 1.0005,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            alert_note=whale_note,
            bybit_funding_rate=state.bybit_fr,
            bybit_next_funding_ts=state.bybit_next_funding_ts,
            bybit_fr_interval_hours=state.bybit_fr_interval_hours,
            state=state,
        )

        logger.info(
            "🚨 SETUP C TETİKLENDİ: %s %s güven=%.0f%%",
            state.symbol, direction.value, score * 100,
        )

        return signal

    def _calc_levels(
        self, state: AggregatedState, direction: Direction
    ) -> tuple:
        price = state.price

        if direction == Direction.LONG:
            entry = price
            sl = price * 0.997       # %0.3 altı (scalp = dar SL)
            tp1 = price * 1.007      # %0.7 yukarı
            tp2 = price * 1.015      # %1.5 yukarı
        else:
            entry = price
            sl = price * 1.003
            tp1 = price * 0.993
            tp2 = price * 0.985

        return entry, sl, tp1, tp2
