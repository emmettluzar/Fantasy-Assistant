"""Platform adapters for the Fantasy Draft Assistant.

Each adapter normalizes a platform's native draft/league data into the
canonical ``DRAFT_PICK_MADE`` payload shape understood by the engine. Adapters
are optional-runtime: they import their platform SDK lazily so the sidecar can
run without those packages installed (e.g. in CI or the offline fallback).
"""

from .espn import EspnAdapter
from .normalizer import NormalizedPlayer, PlayerNormalizer
from .sleeper import SleeperAdapter
from .yahoo import YahooAdapter

__all__ = [
    "EspnAdapter",
    "NormalizedPlayer",
    "PlayerNormalizer",
    "SleeperAdapter",
    "YahooAdapter",
]