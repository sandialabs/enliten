"""Small, dependency-free common definitions for unit-commitment studies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Site:
    """A connection point shared by assets.

    ``POI_limit`` is optional and constrains power delivered from the site to
    load or grid. Weather and resource modelling belong upstream: pass its
    resulting time series to :class:`enliten.generation.Generation`.
    """

    name: str
    POI_limit: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Site.name must be non-empty.")
        if self.POI_limit is not None and self.POI_limit < 0:
            raise ValueError("Site.POI_limit must be non-negative.")
