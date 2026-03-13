"""
Trade Bot — Logging Configuration
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO"):
    """Merkezi loglama yapılandırması."""
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    log_format = "[%(asctime)s] %(levelname)-8s %(name)-25s %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(log_dir / "trade_bot.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(file_handler)

    # Gürültülü kütüphaneleri sustur
    for noisy in ("websockets", "aiohttp", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info("Logging yapılandırıldı — seviye: %s", level)
