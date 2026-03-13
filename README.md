# Trade Bot — Kripto Sinyal Motoru

## Mimari
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

## Kurulum

```bash
# 1. Sanal ortam oluştur
python -m venv .venv
source .venv/bin/activate  # Linux/Mac

# 2. Bağımlılıkları yükle
pip install -r requirements.txt

# 3. Ortam değişkenlerini ayarla
cp .env.example .env
# .env dosyasını düzenle: Telegram token/chat id, opsiyonel CryptoPanic API key

# 4. Başlat
python main.py
```

## Sinyal Setup'ları

| Setup | İsim | Koşullar | Tür |
|-------|------|----------|-----|
| A | Reversal / Sweep | Likidasyon havuzu sweep + OI düşüşü + Taker flip + CVD patlama | Scalp / Day Trade |
| B | Divergence / Trap | OI artış + Futures CVD ↔ Spot CVD uyumsuzluğu + FR extreme | Day Trade |
| C | Momentum / Whale | CVD çift yönlü %50+ spike + Whale agresyonu | Scalp |

## Not
Bu bot **işlem açmaz**, yalnızca Telegram üzerinden A-Kalite sinyal gönderir.

## Konfigürasyon Notları

- Borsa verileri public API üzerinden alınır, borsa API key gerekmez.
- `SYMBOLS=auto` ayarı ile Bybit USDT perpetual sembolleri otomatik çekilir.
- Telegram mesajı için `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` zorunludur.
- `CRYPTOPANIC_API_KEY` boş bırakılırsa haber servisi "ulaşılamıyor/ayarsız" olarak raporlanır.

## GitHub'a Gönderim (Güvenli)

```bash
# 1) Repo başlat
git init

# 2) Hassas verileri kontrol et (.env commit ETME)
git status

# 3) Dosyaları ekle
git add .

# 4) İlk commit
git commit -m "Initial commit"

# 5) GitHub remote ekle
git remote add origin <REPO_URL>

# 6) Push
git branch -M main
git push -u origin main
```
