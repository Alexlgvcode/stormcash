"""Everything a request or background task needs, built once per app."""

from __future__ import annotations

from dataclasses import dataclass, field

from psycopg_pool import ConnectionPool

from .config import Settings
from .detectors import DetectorState
from .nessie import MoneyMover, NessieClient
from .sse import Broker


@dataclass
class Deps:
    settings: Settings
    pool: ConnectionPool
    events: Broker
    nessie: NessieClient | None  # None when Nessie is switched off (ledger-only)
    mover: MoneyMover
    detector_state: DetectorState = field(default_factory=DetectorState)

    @property
    def server_key(self):
        return self.settings.server_key
