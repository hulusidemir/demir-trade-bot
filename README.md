# Demir Trade Bot — Crypto Signal Engine

## Architecture
```
                    ┌────────────┐
                    │  Telegram   │
                    │    Bot      │
                    └─────▲──────┘
                          │ Signal
                    ┌─────┴──────┐
                    │   Signal    │
                    │  Manager    │
                    │ (A / B / C) │
                    └─────▲──────┘
                          │ AggregatedState
                    ┌─────┴──────┐
        ┌───────────┤ Aggregator ├───────────┐
        │           └─────▲──────┘           │
        │                 │                  │
   ┌────┴────┐      ┌────┴────┐       ┌────┴────┐
   │Indicators│     │Indicators│      │Indicators│
   │ OI, CVD  │     │Orderbook │      │ Whale,   │
   │ FR, Taker│     │+Spoofing │      │ Liq      │
   └────▲────┘      └────▲────┘       └────▲────┘
        │                 │                  │
   ┌────┴────┐      ┌────┴────┐       ┌────┴────┐
   │ Binance  │     │  Bybit   │      │OKX/CB/KR│
   │ WS+REST  │     │ WS+REST  │      │ WS+REST  │
   └──────────┘     └──────────┘       └──────────┘
```

## Setup

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env: Telegram token/chat id, optional CryptoPanic API key

# 4. Run
python main.py
```

## Signal Setups

| Setup | Name | Conditions | Type |
|-------|------|----------|-----|
| A | Reversal / Sweep | Liquidation pool sweep + OI drop + taker ratio flip + CVD spike | Scalp / Day Trade |
| B | Divergence / Trap | OI increase + Futures CVD ↔ Spot CVD divergence + extreme FR | Day Trade |
| C | Momentum / Whale | Bi-directional CVD 50%+ spike + whale aggression | Scalp |

## Note
This bot **does not open trades**; it only sends A-grade signals via Telegram.

## Configuration Notes

- Exchange data is fetched via public APIs; no exchange API key is required.
- With `SYMBOLS=auto`, all Bybit USDT perpetual symbols are fetched automatically.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are required for Telegram alerts.
- If `CRYPTOPANIC_API_KEY` is empty, the news service is reported as unavailable/unconfigured.

