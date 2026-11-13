"""Limitador de peticiones en memoria para comandos costosos.

No pretende sustituir un limitador distribuido: el bot se ejecuta en una sola
instancia. Su objetivo es evitar que un usuario sature búsquedas, descargas o
mantenimiento con pulsaciones repetidas.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class SlidingWindowLimiter:
    _events: Dict[str, list[float]] = field(default_factory=dict)

    def allow(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, float]:
        now = time.monotonic()
        window = max(1, int(window_seconds))
        limit = max(1, int(limit))
        cutoff = now - window

        timestamps = [ts for ts in self._events.get(key, []) if ts >= cutoff]
        if len(timestamps) >= limit:
            retry_after = max(0.0, timestamps[0] + window - now)
            self._events[key] = timestamps
            return False, retry_after

        timestamps.append(now)
        self._events[key] = timestamps
        return True, 0.0

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)


search_limiter = SlidingWindowLimiter()
download_limiter = SlidingWindowLimiter()
maintenance_limiter = SlidingWindowLimiter()


def human_retry_after(seconds: float) -> str:
    seconds = max(1, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    return f"{max(1, seconds // 60)} min"
