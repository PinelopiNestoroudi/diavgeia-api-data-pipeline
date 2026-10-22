"""Small process-local snapshot store; no persistent search history."""

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from src.processing.validation import validate_normalized


class SnapshotUnavailable(LookupError):
    """Unknown, expired or evicted snapshot."""


@dataclass(frozen=True)
class Snapshot:
    rows: tuple
    complete: bool
    deadline: float
    expires_at: str


class SnapshotStore:
    def __init__(self, ttl=600, capacity=5, clock=time.monotonic, wall_clock=time.time):
        self.ttl, self.capacity = ttl, capacity
        self.clock, self.wall_clock = clock, wall_clock
        self._items = {}
        self._lock = threading.Lock()

    def _expire(self, now):
        self._items = {key: value for key, value in self._items.items() if value.deadline > now}

    def create(self, result):
        rows = tuple(MappingProxyType(validate_normalized(row)) for row in result.rows)
        with self._lock:
            now = self.clock()
            self._expire(now)
            if len(self._items) >= self.capacity:
                del self._items[next(iter(self._items))]
            snapshot_id = secrets.token_urlsafe(16)
            expires_at = datetime.fromtimestamp(self.wall_clock() + self.ttl, timezone.utc).isoformat()
            snapshot = Snapshot(rows, result.complete, now + self.ttl, expires_at)
            self._items[snapshot_id] = snapshot
        return snapshot_id, snapshot

    def get(self, snapshot_id):
        with self._lock:
            self._expire(self.clock())
            snapshot = self._items.get(snapshot_id) if isinstance(snapshot_id, str) else None
            if snapshot is None:
                raise SnapshotUnavailable("Snapshot unavailable or expired. Search again.")
            return snapshot
