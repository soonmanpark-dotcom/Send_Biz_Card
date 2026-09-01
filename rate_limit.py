"""발송 횟수 제한.

시크릿이 유출되더라도 대량 발송으로 이어지지 않도록 세 가지 한도를 둔다.
서버 메모리에만 기록하므로 재시작하면 초기화된다. 개인용 봇 규모에서는
데이터베이스를 두는 것보다 이 편이 단순하고 충분하다.
"""

import time
from collections import deque
from threading import Lock

HOUR = 3600
DAY = 86400


class RateLimiter:
    def __init__(self, limits: dict | None = None):
        limits = limits or {}
        self.per_recipient_hour = int(limits.get("per_recipient_per_hour", 3))
        self.total_hour = int(limits.get("total_per_hour", 20))
        self.total_day = int(limits.get("total_per_day", 50))
        self._all: deque[float] = deque()
        self._by_recipient: dict[str, deque[float]] = {}
        self._lock = Lock()

    @staticmethod
    def _trim(dq: deque, now: float, window: int) -> None:
        while dq and now - dq[0] > window:
            dq.popleft()

    def check_and_record(self, recipient: str):
        """허용되면 기록하고 None 을, 한도를 넘으면 사유를 돌려준다."""
        now = time.time()
        key = recipient.strip().lower()
        with self._lock:
            self._trim(self._all, now, DAY)
            dq = self._by_recipient.setdefault(key, deque())
            self._trim(dq, now, HOUR)

            if len(dq) >= self.per_recipient_hour:
                return "recipient"
            if sum(1 for t in self._all if now - t <= HOUR) >= self.total_hour:
                return "hour"
            if len(self._all) >= self.total_day:
                return "day"

            self._all.append(now)
            dq.append(now)

            # 오래된 수신자 항목이 쌓이지 않도록 가끔 정리한다.
            if len(self._by_recipient) > 1000:
                for k in [k for k, v in self._by_recipient.items()
                          if not v or now - v[-1] > HOUR]:
                    del self._by_recipient[k]
            return None

    def snapshot(self) -> dict:
        """진단용 현재 사용량."""
        now = time.time()
        with self._lock:
            self._trim(self._all, now, DAY)
            return {
                "sent_last_hour": sum(1 for t in self._all if now - t <= HOUR),
                "sent_last_day": len(self._all),
                "limits": {
                    "per_recipient_per_hour": self.per_recipient_hour,
                    "total_per_hour": self.total_hour,
                    "total_per_day": self.total_day,
                },
            }
