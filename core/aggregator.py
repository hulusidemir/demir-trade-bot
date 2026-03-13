"""
Trade Bot — Aggregation Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tüm borsalardan gelen veriyi:
  1. Toplar (Indicator modülleri üzerinden)
  2. AggregatedState oluşturur
  3. SignalManager'a gönderir
  4. Sinyal varsa Telegram'a iletir

Bu dosya tüm sistemin kalbi — veri akış orkestratörü.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Callable, Coroutine, Dict, List, Optional

from config import settings
from core.models import (
    AggregatedState,
    FundingRateData,
    LiquidationData,
    OpenInterestData,
    OrderbookSnapshot,
    Signal,
    TradeData,
)
from indicators.cvd import CVDCalculator
from indicators.funding_rate import FundingRateAnalyzer
from indicators.liquidations import LiquidationTracker
from indicators.open_interest import OpenInterestTracker
from indicators.orderbook import OrderbookAnalyzer
from indicators.taker_ratio import TakerRatioTracker
from indicators.whale_detector import WhaleDetector
from signals.signal_manager import SignalManager

logger = logging.getLogger("core.aggregator")

# Sinyal callback tipi
SignalCallback = Callable[[Signal], Coroutine]


class Aggregator:
    """
    Merkezi veri toplama ve analiz motoru.
    Tüm indicator'ları besler, periyodik olarak state oluşturur ve sinyalleri tetikler.
    """

    def __init__(self):
        # İndikatörler
        self.oi_tracker = OpenInterestTracker()
        self.cvd_calc = CVDCalculator()
        self.ob_analyzer = OrderbookAnalyzer(
            spoof_price_pct=settings.thresholds.spoof_price_pct,
            spoof_ttl_sec=settings.thresholds.spoof_ttl_sec,
        )
        self.taker_tracker = TakerRatioTracker()
        self.fr_analyzer = FundingRateAnalyzer(
            arb_threshold=settings.thresholds.fr_arb_diff,
        )
        self.liq_tracker = LiquidationTracker()
        self.whale_detector = WhaleDetector(
            std_multiplier=settings.thresholds.whale_std_multiplier,
        )
        self.signal_manager = SignalManager(
            min_confidence=settings.thresholds.min_signal_confidence,
        )

        # Son fiyatlar: {symbol: deque[(ts, price)]}
        self._prices: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10_000))

        # Sinyal callback
        self.on_signal: Optional[SignalCallback] = None

        # Evaluation lock (aynı anda birden fazla eval çalışmasın)
        self._eval_lock = asyncio.Lock()

    # ══════════════════════════════════════════════
    #  Data Ingestion Callbacks (Borsalar bunları çağırır)
    # ══════════════════════════════════════════════

    async def on_trade(self, trade: TradeData):
        """Bir trade geldiğinde çağrılır."""
        # Fiyat güncelle
        self._prices[trade.symbol].append((trade.timestamp, trade.price))

        # CVD hesapla
        self.cvd_calc.on_trade(trade)

        # Taker ratio güncelle
        self.taker_tracker.on_trade(trade)

        # Whale detection
        whale_event = self.whale_detector.on_trade(trade)
        if whale_event:
            logger.info("Whale event tespit edildi: %s", whale_event)

    async def on_orderbook(self, ob: OrderbookSnapshot):
        """Orderbook güncellemesi geldiğinde çağrılır."""
        price = self._get_current_price(ob.symbol)
        if price > 0:
            self.ob_analyzer.update(ob, price)

    async def on_liquidation(self, liq: LiquidationData):
        """Likidasyon verisi geldiğinde çağrılır."""
        self.liq_tracker.on_liquidation(liq)

    async def on_open_interest(self, oi: OpenInterestData):
        """OI verisi geldiğinde çağrılır."""
        self.oi_tracker.update(oi)

    async def on_funding_rate(self, fr: FundingRateData):
        """Funding rate verisi geldiğinde çağrılır."""
        self.fr_analyzer.update(fr)

    # ══════════════════════════════════════════════
    #  Periyodik Evaluation Loop
    # ══════════════════════════════════════════════

    async def run_evaluation_loop(self, interval_sec: float = 5.0):
        """
        Her `interval_sec` saniyede bir tüm semboller için
        AggregatedState oluştur ve sinyalleri değerlendir.
        """
        logger.info("Evaluation loop başlatılıyor (aralık: %.1fs)…", interval_sec)

        while True:
            try:
                await asyncio.sleep(interval_sec)

                for symbol in settings.symbols:
                    async with self._eval_lock:
                        state = self._build_state(symbol)
                        if state.price <= 0:
                            continue  # Henüz veri yok

                        signal = self.signal_manager.evaluate(state)
                        if signal:
                            await self._emit_signal(signal)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Evaluation loop hatası: %s", exc, exc_info=True)
                await asyncio.sleep(5)

    # ══════════════════════════════════════════════
    #  State Builder
    # ══════════════════════════════════════════════

    def _build_state(self, symbol: str) -> AggregatedState:
        """Tüm indikatörlerden sembol bazlı snapshot oluştur."""
        now = time.time()
        price = self._get_current_price(symbol)

        # OI
        total_oi, oi_change_pct, oi_by_exchange = self.oi_tracker.get_aggregated(symbol)

        # CVD
        spot_cvd = self.cvd_calc.get_spot_cvd(symbol, window_sec=60)
        futures_cvd = self.cvd_calc.get_futures_cvd(symbol, window_sec=60)
        spot_cvd_chg, fut_cvd_chg = self.cvd_calc.get_cvd_change_pct(symbol, window_sec=60)

        # Orderbook
        bid_depth, ask_depth, imbalance = (0.0, 0.0, 0.0)
        if price > 0:
            bid_depth, ask_depth, imbalance = self.ob_analyzer.get_aggregated_depth(symbol, price)

        # Taker
        taker_ratio, taker_buy, taker_sell = self.taker_tracker.get_ratio(symbol, window_sec=60)
        # Önceki periyot taker ratio
        prev_ratio, _, _ = self.taker_tracker.get_ratio(symbol, window_sec=120)

        # Funding Rate
        agg_fr, bybit_fr, fr_arb, fr_by_ex = self.fr_analyzer.get_rates(symbol)
        bybit_next_ts, bybit_fr_interval = self.fr_analyzer.get_bybit_meta(symbol)

        # Likidasyonlar
        long_liqs, short_liqs = self.liq_tracker.get_recent_volume(symbol, window_sec=120)

        # Whale
        whale_events = self.whale_detector.get_recent_whale_events(symbol, window_sec=120)

        # Fiyat değişim yüzdeleri
        pct_1m = self._price_change_pct(symbol, 60)
        pct_5m = self._price_change_pct(symbol, 300)
        pct_15m = self._price_change_pct(symbol, 900)
        pct_1h = self._price_change_pct(symbol, 3600)

        return AggregatedState(
            symbol=symbol,
            timestamp=now,
            total_oi=total_oi,
            oi_change_pct=oi_change_pct,
            oi_by_exchange=oi_by_exchange,
            spot_cvd=spot_cvd,
            futures_cvd=futures_cvd,
            spot_cvd_change_pct=spot_cvd_chg,
            futures_cvd_change_pct=fut_cvd_chg,
            total_bid_depth=bid_depth,
            total_ask_depth=ask_depth,
            bid_ask_imbalance=imbalance,
            taker_buy_vol=taker_buy,
            taker_sell_vol=taker_sell,
            taker_ratio=taker_ratio,
            taker_ratio_prev=prev_ratio,
            aggregated_fr=agg_fr,
            bybit_fr=bybit_fr,
            bybit_next_funding_ts=bybit_next_ts,
            bybit_fr_interval_hours=bybit_fr_interval,
            fr_arb_spread=fr_arb,
            fr_by_exchange=fr_by_ex,
            total_long_liqs=long_liqs,
            total_short_liqs=short_liqs,
            whale_events=whale_events,
            price=price,
            price_change_pct_1m=pct_1m,
            price_change_pct_5m=pct_5m,
            price_change_pct_15m=pct_15m,
            price_change_pct_1h=pct_1h,
        )

    # ══════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════

    def _get_current_price(self, symbol: str) -> float:
        series = self._prices.get(symbol)
        if series:
            return series[-1][1]
        return 0.0

    def _price_change_pct(self, symbol: str, window_sec: float) -> float:
        series = self._prices.get(symbol)
        if not series:
            return 0.0

        current = series[-1][1]
        cutoff = time.time() - window_sec

        prev = current
        for ts, p in reversed(series):
            if ts <= cutoff:
                prev = p
                break

        if prev == 0:
            return 0.0
        return ((current - prev) / prev) * 100

    async def _emit_signal(self, signal: Signal):
        """Sinyali callback üzerinden Telegram'a gönder."""
        logger.info(
            "📡 SİNYAL: %s %s %s %s güven=%.0f%%",
            signal.symbol, signal.setup.value, signal.direction.value,
            signal.signal_type.value, signal.confidence * 100,
        )
        if self.on_signal:
            try:
                await self.on_signal(signal)
            except Exception as exc:
                logger.error("Sinyal gönderim hatası: %s", exc, exc_info=True)
