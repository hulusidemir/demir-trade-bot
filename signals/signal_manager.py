"""
Trade Bot — Signal Manager
Tüm setup detektörlerini koordine eder.
Cooldown, duplicate ve minimum güven kontrolü yapar.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional

from core.models import AggregatedState, Signal
from signals.setup_a import SetupADetector
from signals.setup_b import SetupBDetector
from signals.setup_c import SetupCDetector

logger = logging.getLogger("signal.manager")

# Aynı sembol/setup için minimum bekleme süresi (saniye)
_COOLDOWN = {
    "SETUP_A": 300,   # 5 dakika
    "SETUP_B": 600,   # 10 dakika
    "SETUP_C": 180,   # 3 dakika
}


class SignalManager:
    """
    Sinyal yöneticisi.
    - Her tick'te 3 setup'ı da değerlendirir.
    - Cooldown kontrolü yapar (spam önleme).
    - Minimum güven skoru kontrolü.
    """

    def __init__(self, min_confidence: float = 0.75):
        self.setup_a = SetupADetector(min_confidence=min_confidence)
        self.setup_b = SetupBDetector(min_confidence=min_confidence)
        self.setup_c = SetupCDetector(min_confidence=min_confidence)

        # {(symbol, setup_type): last_signal_timestamp}
        self._last_signal: Dict[tuple, float] = defaultdict(float)

        # Sinyal geçmişi
        self.history: List[Signal] = []

    def evaluate(self, state: AggregatedState) -> Optional[Signal]:
        """
        AggregatedState'i tüm setup'larla değerlendir.
        En yüksek güvenli sinyali döndür.
        """
        candidates: List[Signal] = []

        # Her setup'ı değerlendir
        for detector in [self.setup_a, self.setup_b, self.setup_c]:
            try:
                sig = detector.evaluate(state)
                if sig and self._check_cooldown(sig):
                    candidates.append(sig)
            except Exception as exc:
                logger.error("Setup değerlendirme hatası: %s", exc, exc_info=True)

        if not candidates:
            return None

        # En yüksek güvenli sinyali seç
        best = max(candidates, key=lambda s: s.confidence)

        # Kaydet
        self._last_signal[(best.symbol, best.setup.value)] = time.time()
        self.history.append(best)

        # Geçmişi sınırla (son 1000 sinyal)
        if len(self.history) > 1000:
            self.history = self.history[-500:]

        return best

    def _check_cooldown(self, sig: Signal) -> bool:
        """Aynı sembol/setup için cooldown kontrolü."""
        key = (sig.symbol, sig.setup.value)
        cooldown = _COOLDOWN.get(sig.setup.value, 300)
        elapsed = time.time() - self._last_signal[key]

        if elapsed < cooldown:
            logger.debug(
                "Cooldown: %s %s (kalan: %.0fs)",
                sig.symbol, sig.setup.value, cooldown - elapsed,
            )
            return False
        return True
