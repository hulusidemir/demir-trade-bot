#!/usr/bin/env python3
"""
Trade Bot — Entry Point
━━━━━━━━━━━━━━━━━━━━━━━
Kripto piyasalarını izleyen, A-Kalite sinyal üreten
ve Telegram'a gönderen algoritmik analiz motoru.

Kullanım:
    python main.py

Not: Bot işlem AÇMAZ, yalnızca sinyal gönderir.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

# Proje kök dizinini PYTHONPATH'e ekle
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings
from core.engine import Engine
from utils.logger import setup_logging


def main():
    """Ana giriş noktası."""

    # Logging'i yapılandır
    setup_logging(settings.log_level)

    # Validasyon
    if not settings.telegram.bot_token:
        print(
            "⚠️  TELEGRAM_BOT_TOKEN ayarlanmamış!\n"
            "    .env.example dosyasını .env olarak kopyalayıp ayarlayın.\n"
            "    Bot yine de çalışacak ama sinyaller sadece log'a yazılacak."
        )

    if not settings.is_auto_symbols and not settings.symbols:
        print("❌ İzlenecek sembol tanımlanmamış! .env dosyasında SYMBOLS=auto veya sembol listesi ayarlayın.")
        sys.exit(1)

    if settings.is_auto_symbols:
        print("🔄 Auto-symbol modu: Bybit'ten tüm USDT perp semboller çekilecek.")

    # Engine'i başlat
    engine = Engine()

    # Graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown_handler():
        print("\n🛑 Kapatılıyor…")
        engine.set_shutdown_reason(
            "Kullanıcı durdurması",
            "İşletim sistemi sinyal ile durdurma isteği gönderdi (SIGINT/SIGTERM)."
        )
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown_handler)
        except NotImplementedError:
            # Windows'ta çalışmaz
            pass

    try:
        loop.run_until_complete(engine.start())
    except KeyboardInterrupt:
        print("\n🛑 Kullanıcı tarafından durduruldu.")
        engine.set_shutdown_reason(
            "Klavye kesintisi",
            "Kullanıcı Ctrl+C ile botu durdurdu."
        )
        # Shutdown mesajını gönder
        loop.run_until_complete(engine._send_shutdown_message())
    except Exception as exc:
        print(f"\n💥 Beklenmeyen hata: {exc}")
        engine.set_shutdown_reason(
            "Beklenmeyen hata (main)",
            f"{type(exc).__name__}: {exc}"
        )
        loop.run_until_complete(engine._send_shutdown_message())
    finally:
        # Tüm bekleyen görevleri temizle
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


if __name__ == "__main__":
    main()
