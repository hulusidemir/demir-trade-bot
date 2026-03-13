"""
Trade Bot — Telegram Sinyal Botu
Zorunlu çıktı formatına uygun mesaj gönderir.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from config import settings
from core.models import Direction, Signal, SignalType, SetupType

logger = logging.getLogger("telegram.bot")


class TelegramBot:
    """
    Telegram mesaj gönderici.
    python-telegram-bot kütüphanesi yerine doğrudan HTTP API kullanır
    (daha az bağımlılık, daha hızlı).
    """

    API_BASE = "https://api.telegram.org/bot{token}"

    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token or settings.telegram.bot_token
        self.chat_id = chat_id or settings.telegram.chat_id
        self.base_url = self.API_BASE.format(token=self.token)

    async def send_signal(self, signal: Signal, news_context: str = ""):
        """Sinyali formatlayıp Telegram'a gönder."""
        message = self._format_signal(signal, news_context)
        await self._send_message(message)

    async def send_alert(self, text: str):
        """Basit uyarı mesajı gönder."""
        await self._send_message(text)

    # ══════════════════════════════════════════════
    #  Mesaj Formatlayıcı — ZORUNLU FORMAT
    # ══════════════════════════════════════════════

    def _format_signal(self, sig: Signal, news_context: str = "") -> str:
        """
        Zorunlu Telegram çıktı formatı.
        Belirsiz kelimeler ("Yükselebilir", "İhtimal var") YASAK.
        """

        # ── Başlık ──
        if sig.signal_type == SignalType.SCALP:
            header = "⚡ [SCALP İŞLEM] UYARISI"
        else:
            header = "📊 [DAY TRADE İŞLEMİ] UYARISI"

        symbol_clean = sig.symbol.replace("/", "")
        direction_emoji = "🟢" if sig.direction == Direction.LONG else "🔴"
        direction_text = sig.direction.value

        # ── Setup ismi ──
        setup_names = {
            SetupType.A_REVERSAL: "Reversal / Sweep",
            SetupType.B_DIVERGENCE: "Divergence / Trap",
            SetupType.C_MOMENTUM: "Momentum / Whale Aggression",
        }
        setup_name = setup_names.get(sig.setup, sig.setup.value)

        # ── Acil Durum Uyarısı ──
        alert_section = ""
        if sig.alert_note:
            alert_section = f"\n🚨 ACİL DURUM UYARISI:\n{sig.alert_note}"

        # ── Piyasa Röntgeni ──
        news_line = news_context if news_context else "Kritik haber tespit edilmedi."
        sector_line = sig.sector_note if sig.sector_note else "Sektör analizi yükleniyor…"
        btc_line = sig.btc_correlation_note if sig.btc_correlation_note else "BTC korelasyonu hesaplanıyor…"

        # ── Teknik ve Veri Otopsisi ──
        technical = sig.technical_note if sig.technical_note else self._auto_technical(sig)

        # ── Savaş Planı ──
        entry_str = f"${sig.entry_low:,.2f} — ${sig.entry_high:,.2f}"
        sl_str = f"${sig.stop_loss:,.2f}"
        tp1_str = f"${sig.tp1:,.2f}"
        tp2_str = f"${sig.tp2:,.2f}"

        # FR satırı: rate + kalan süre + interval
        fr_line = self._format_fr_line(sig)

        # Profesyonel not
        pro_note = sig.pro_note if sig.pro_note else self._auto_pro_note(sig)

        # ── Tam Mesaj ──
        msg = f"""
{header}
{'━' * 30}
{direction_emoji} {symbol_clean} — {direction_text} | {setup_name}
Güven: {'█' * int(sig.confidence * 10)}{'░' * (10 - int(sig.confidence * 10))} {sig.confidence * 100:.0f}%
{alert_section}

📊 PİYASA RÖNTGENİ:
├ Haber/Dış Etken: {news_line}
├ Sektör: {sector_line}
└ BTC Korelasyonu: {btc_line}

📉 TEKNİK VE VERİ OTOPSİSİ:
{technical}

🎯 SAVAŞ PLANI:
├ Karar: KESİN OLARAK {direction_text}
├ Giriş Bölgesi: {entry_str}
├ Geçersiz Kılınma (SL): {sl_str}
├ Hedef TP1: {tp1_str}
├ Hedef TP2: {tp2_str}
└ {fr_line}

💡 Profesyonel Not:
{pro_note}

⏰ Sinyal Zamanı: {self._format_time(sig.timestamp)}
{'━' * 30}
"""
        return msg.strip()

    def _auto_technical(self, sig: Signal) -> str:
        """State'ten otomatik teknik analiz metni üret."""
        if not sig.state:
            return "Veri yetersiz."

        s = sig.state
        lines = []

        # CVD durumu
        if s.spot_cvd > 0 and s.futures_cvd < 0:
            lines.append(
                f"Spot CVD agresif yükselirken, perakende vadeli shortluyor."
            )
        elif s.spot_cvd < 0 and s.futures_cvd > 0:
            lines.append(
                f"Spot CVD düşerken, vadeli tarafta long pozisyonlar açılıyor."
            )

        # OI durumu
        if s.oi_change_pct <= -3:
            lines.append(
                f"OI son 1 dk'da {s.oi_change_pct:+.1f}% düştü → Likidasyonlar tetiklendi."
            )
        elif s.oi_change_pct >= 3:
            lines.append(
                f"OI son 1 dk'da {s.oi_change_pct:+.1f}% arttı → Yeni pozisyonlar açılıyor."
            )

        # Likidasyon
        total_liqs = s.total_long_liqs + s.total_short_liqs
        if total_liqs > 100_000:
            lines.append(
                f"Son 2 dk likidasyon: Long ${s.total_long_liqs:,.0f} / Short ${s.total_short_liqs:,.0f}"
            )

        # FR + countdown + interval
        fr_text = f"Bybit FR: {s.bybit_fr:+.4%}"
        if s.bybit_next_funding_ts > 0:
            import time as _time
            remaining = s.bybit_next_funding_ts - _time.time()
            if remaining > 0:
                hrs, rem = divmod(int(remaining), 3600)
                mins, secs = divmod(rem, 60)
                fr_text += f" | Sonraki: {hrs}s {mins}dk {secs}sn"
            else:
                fr_text += " | Fonlama şimdi uygulanıyor"
        if s.bybit_fr_interval_hours:
            fr_text += f" | İnterval: {s.bybit_fr_interval_hours}h"
        lines.append(fr_text)

        if s.fr_arb_spread > 0.005:
            lines.append(f"FR Arbitraj Uçurumu: {s.fr_arb_spread:.4%}")

        # Whale
        if s.whale_events:
            w = s.whale_events[-1]
            lines.append(
                f"Whale Agresyon: {w.exchange.upper()} ${w.volume:,.0f} taker {w.side} ({w.std_multiplier:.1f}σ)"
            )

        # Orderbook
        if abs(s.bid_ask_imbalance) > 0.1:
            side = "BID ağırlıklı (Alıcı)" if s.bid_ask_imbalance > 0 else "ASK ağırlıklı (Satıcı)"
            lines.append(f"Orderbook: {side} (imbalance: {s.bid_ask_imbalance:+.2f})")

        return "\n".join(f"  {line}" for line in lines) if lines else "  Veri toplanıyor…"

    def _format_fr_line(self, sig: Signal) -> str:
        """FR + kalan süre + interval bilgisi."""
        import time as _time
        rate_str = f"Bybit FR: {sig.bybit_funding_rate:+.4%}"
        if sig.bybit_next_funding_ts > 0:
            remaining = sig.bybit_next_funding_ts - _time.time()
            if remaining > 0:
                hrs, rem = divmod(int(remaining), 3600)
                mins, secs = divmod(rem, 60)
                rate_str += f" | Sonraki fonlama: {hrs}s {mins}dk {secs}sn"
            else:
                rate_str += " | Fonlama şimdi uygulanıyor"
        if sig.bybit_fr_interval_hours:
            rate_str += f" | İnterval: {sig.bybit_fr_interval_hours}h"
        return rate_str

    def _auto_pro_note(self, sig: Signal) -> str:
        """Otomatik profesyonel not."""
        notes = []

        if sig.state:
            s = sig.state
            # Spot CVD uyarısı
            if sig.direction == Direction.LONG and s.spot_cvd < 0:
                notes.append("Spottaki alım henüz başlamadı, işleme dikkatli gir.")
            elif sig.direction == Direction.SHORT and s.spot_cvd > 0:
                notes.append("Spottaki alım devam ediyor, erken short riskli.")

            # Orderbook uyarısı
            if abs(s.bid_ask_imbalance) < 0.05:
                notes.append("Orderbook nötr — sahte duvar riski var, derinliğe güvenme.")

            # FR uyarısı
            if abs(s.bybit_fr) > 0.015:
                notes.append(f"FR aşırı uçta ({s.bybit_fr:+.4%}), squeeze bekle.")

        if not notes:
            notes.append("SL seviyeni kesinlikle koy, disiplinden sapma.")

        return "  " + "\n  ".join(notes)

    @staticmethod
    def _format_time(ts: float) -> str:
        import datetime
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    # ══════════════════════════════════════════════
    #  HTTP Gönderim
    # ══════════════════════════════════════════════

    async def _send_message(self, text: str, parse_mode: str = ""):
        if not self.token or not self.chat_id:
            logger.warning("Telegram token/chat_id ayarlanmamış, mesaj gönderilemiyor.")
            logger.info("TELEGRAM MESAJI:\n%s", text)
            return

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("Telegram mesajı gönderildi.")
                    else:
                        body = await resp.text()
                        logger.error("Telegram hatası %d: %s", resp.status, body)
        except Exception as exc:
            logger.error("Telegram gönderim hatası: %s", exc)
