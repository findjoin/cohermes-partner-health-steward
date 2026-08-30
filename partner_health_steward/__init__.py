"""Current Partner Health Plugin implementation surface.

This package is intentionally independent from the historical ``ops`` tree.
It exposes only the synthetic Plugin -> health-core seam needed by Ticket 110.
"""

from .acceptance_run import AcceptanceRunContract
from .core import HealthCore
from .host_contract import HostReleaseContract
from .plugin import HealthPlugin
from .production_core_service import ProductionCoreService
from .release_deployment import DefaultOnlyGateExecutor, HermesReleasePublisher

__all__ = [
    "AcceptanceRunContract",
    "HealthCore",
    "HealthPlugin",
    "ProductionCoreService",
    "HostReleaseContract",
    "HermesReleasePublisher",
    "DefaultOnlyGateExecutor",
]
