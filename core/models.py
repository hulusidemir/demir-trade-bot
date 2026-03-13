"""
Trade Bot — Veri Modelleri
Tüm veri yapıları (dataclass) burada tanımlanır.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ──────────────────────────────────────────────
#  Enum Tanımları
# ──────────────────────────────────────────────

class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalType(str, Enum):
    SCALP = "SCALP İŞLEM"
    DAYTRADE = "DAY TRADE İŞLEMİ"


class SetupType(str, Enum):
    A_REVERSAL = "SETUP_A"
    B_DIVERGENCE = "SETUP_B"
    C_MOMENTUM = "SETUP_C"


# ──────────────────────────────────────────────
#  Orderbook Verisi
# ──────────────────────────────────────────────

@dataclass
class OrderbookLevel:
    price: float
    quantity: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class OrderbookSnapshot:
    exchange: str
    symbol: str
    bids: List[OrderbookLevel] = field(default_factory=list)
    asks: List[OrderbookLevel] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Trade (İşlem) Verisi
# ──────────────────────────────────────────────

@dataclass
class TradeData:
    exchange: str
    symbol: str
    price: float
    quantity: float
    is_buyer_maker: bool          # True = seller taker, False = buyer taker
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Open Interest
# ──────────────────────────────────────────────

@dataclass
class OpenInterestData:
    exchange: str
    symbol: str
    value: float                  # USDT cinsinden OI
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Funding Rate
# ──────────────────────────────────────────────

@dataclass
class FundingRateData:
    exchange: str
    symbol: str
    rate: float
    next_funding_time: float = 0.0     # Unix timestamp (saniye)
    funding_interval_hours: int = 8    # Fonlama intervali (saat)
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Likidasyon
# ──────────────────────────────────────────────

@dataclass
class LiquidationData:
    exchange: str
    symbol: str
    side: str                     # "BUY" = short liq., "SELL" = long liq.
    price: float
    quantity: float
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  CVD (Cumulative Volume Delta)
# ──────────────────────────────────────────────

@dataclass
class CVDData:
    symbol: str
    spot_cvd: float = 0.0
    futures_cvd: float = 0.0
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Taker Buy / Sell Oranı
# ──────────────────────────────────────────────

@dataclass
class TakerRatioData:
    symbol: str
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    ratio: float = 1.0            # buy / sell
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Whale Aggression
# ──────────────────────────────────────────────

@dataclass
class WhaleEvent:
    exchange: str
    symbol: str
    side: str                     # "BUY" veya "SELL"
    volume: float
    std_multiplier: float         # Standart sapmanın kaç katı
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
#  Aggregated Market State (Tek Sembol Snapshot)
# ──────────────────────────────────────────────

@dataclass
class AggregatedState:
    symbol: str
    timestamp: float = field(default_factory=time.time)

    # Open Interest
    total_oi: float = 0.0
    oi_change_pct: float = 0.0
    oi_by_exchange: Dict[str, float] = field(default_factory=dict)

    # CVD
    spot_cvd: float = 0.0
    futures_cvd: float = 0.0
    spot_cvd_change_pct: float = 0.0
    futures_cvd_change_pct: float = 0.0

    # Orderbook
    total_bid_depth: float = 0.0
    total_ask_depth: float = 0.0
    bid_ask_imbalance: float = 0.0   # (bid-ask)/(bid+ask)

    # Taker
    taker_buy_vol: float = 0.0
    taker_sell_vol: float = 0.0
    taker_ratio: float = 1.0
    taker_ratio_prev: float = 1.0    # Önceki periyot

    # Funding Rate
    aggregated_fr: float = 0.0
    bybit_fr: float = 0.0
    bybit_next_funding_ts: float = 0.0   # Bir sonraki fonlama zamanı (unix ts)
    bybit_fr_interval_hours: int = 8     # Fonlama intervali (saat)
    fr_arb_spread: float = 0.0           # Max-min FR farkı
    fr_by_exchange: Dict[str, float] = field(default_factory=dict)

    # Likidasyonlar
    total_long_liqs: float = 0.0
    total_short_liqs: float = 0.0
    liq_levels: List[float] = field(default_factory=list)

    # Whale
    whale_events: List[WhaleEvent] = field(default_factory=list)

    # Fiyat
    price: float = 0.0
    price_change_pct_1m: float = 0.0
    price_change_pct_5m: float = 0.0
    price_change_pct_15m: float = 0.0
    price_change_pct_1h: float = 0.0


# ──────────────────────────────────────────────
#  Sinyal
# ──────────────────────────────────────────────

@dataclass
class Signal:
    symbol: str
    setup: SetupType
    signal_type: SignalType
    direction: Direction
    confidence: float              # 0.0 – 1.0

    entry_low: float               # Giriş alt sınır
    entry_high: float              # Giriş üst sınır
    stop_loss: float
    tp1: float
    tp2: float

    # Mesaj parçaları
    alert_note: str = ""           # Acil durum uyarısı
    news_note: str = ""            # Haber bilgisi
    sector_note: str = ""          # Sektör bilgisi
    btc_correlation_note: str = "" # BTC korelasyonu
    technical_note: str = ""       # Teknik ve veri otopsisi
    pro_note: str = ""             # Profesyonel not

    # Bybit FR (zorunlu çıktı)
    bybit_funding_rate: float = 0.0
    bybit_next_funding_ts: float = 0.0   # Bir sonraki fonlama zamanı
    bybit_fr_interval_hours: int = 8     # Fonlama intervali

    timestamp: float = field(default_factory=time.time)

    # İlgili state snapshot
    state: Optional[AggregatedState] = None
