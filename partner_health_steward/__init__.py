"""Current Partner Health Plugin implementation surface.

This package is intentionally independent from the historical ``ops`` tree.
It exposes only the synthetic Plugin -> health-core seam needed by Ticket 110.
"""

from .core import HealthCore
from .plugin import HealthPlugin

__all__ = ["HealthCore", "HealthPlugin"]
