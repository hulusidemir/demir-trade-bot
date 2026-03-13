"""
Trade Bot — Merkezi Konfigürasyon
Tüm ayarlar, eşik değerleri ve API parametreleri burada tanımlanır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

# .env dosyasını yükle
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


# ──────────────────────────────────────────────
#  Telegram
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")


# ──────────────────────────────────────────────
#  Redis
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class RedisConfig:
    host: str = os.getenv("REDIS_HOST", "127.0.0.1")
    port: int = int(os.getenv("REDIS_PORT", "6379"))
    db: int = int(os.getenv("REDIS_DB", "0"))


# ──────────────────────────────────────────────
#  İzlenecek Semboller
# ──────────────────────────────────────────────
def _load_symbols_raw() -> str:
    """Ham sembol değerini döndür. 'auto' ise Bybit'ten çekilecek."""
    return os.getenv("SYMBOLS", "auto").strip()


def _parse_symbols(raw: str) -> List[str]:
    """Virgülle ayrılmış sembol listesini parse et."""
    if raw.lower() == "auto":
        return []  # Engine başlatılırken Bybit'ten çekilecek
    return [s.strip() for s in raw.split(",") if s.strip()]


# ──────────────────────────────────────────────
#  Eşik Değerleri & Sabitler
# ──────────────────────────────────────────────
@dataclass
class Thresholds:
    # Orderbook spoofing filtresi
    spoof_price_pct: float = 1.0           # Fiyata %1'den uzak emirler
    spoof_ttl_sec: float = 5.0             # 5 sn'den kısa yaşayan devasa emirler

    # Whale aggression — standart sapmanın kaç katı
    whale_std_multiplier: float = 4.0

    # OI düşüş eşiği (yüzde) — likidasyon kanıtı
    oi_drop_pct: float = 3.0

    # CVD patlama eşiği (yüzde) — reversal
    cvd_spike_pct: float = 50.0

    # Funding Rate arbitraj fark eşiği
    fr_arb_diff: float = 0.02              # %0.02

    # Taker ratio yön değişim eşiği
    taker_flip_threshold: float = 0.15

    # Sinyal minimum güven skoru (0-1)
    min_signal_confidence: float = 0.75

    # Multi-timeframe pencereler (dakika)
    timeframes: List[str] = field(default_factory=lambda: ["1m", "5m", "15m", "1h"])

    # Scalp vs Day trade sınır (dakika cinsinden)
    scalp_max_tf_minutes: int = 5          # 1m / 5m → scalp
    daytrade_min_tf_minutes: int = 15      # 15m / 1h → day trade


# ──────────────────────────────────────────────
#  Haber Tarama
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class NewsConfig:
    cryptopanic_api_key: str = os.getenv("CRYPTOPANIC_API_KEY", "")
    scan_interval_sec: int = 300           # 5 dakikada bir
    macro_keywords: List[str] = field(
        default_factory=lambda: [
            "CPI", "TÜFE", "FOMC", "Fed", "Interest Rate",
            "Hack", "Exploit", "Token Unlock", "SEC", "regulation",
        ]
    )


# ──────────────────────────────────────────────
#  Master Config (hepsini toparla)
# ──────────────────────────────────────────────
@dataclass
class Settings:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    symbols: List[str] = field(default_factory=lambda: _parse_symbols(_load_symbols_raw()))
    symbols_mode: str = field(default_factory=_load_symbols_raw)  # "auto" veya liste
    thresholds: Thresholds = field(default_factory=Thresholds)
    news: NewsConfig = field(default_factory=NewsConfig)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # Aktif borsalar (public API — key gerekmez)
    active_exchanges: List[str] = field(
        default_factory=lambda: ["binance", "bybit", "okx", "coinbase", "kraken"]
    )

    @property
    def is_auto_symbols(self) -> bool:
        return self.symbols_mode.lower() == "auto"


# Singleton
settings = Settings()
