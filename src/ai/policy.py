from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class CallPolicy:
    min_seconds_between_calls: float = 10 # seconds

    _last_call_ts: float = 0.0
    _last_signature: Optional[str] = None

    def should_call(self, signature: str) -> bool:
        now = time.time()

        # if signature == self._last_signature:
        #     return False
        if (now - self._last_call_ts) < self.min_seconds_between_calls:
            return False

        self._last_call_ts = now
        self._last_signature = signature
        return True
