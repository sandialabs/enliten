"""Technology-agnostic generation assets used by :mod:`enliten.system`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class Generation:
    """An asset with an exogenous power time series.

    ``power_timeseries`` is expressed in MW (and therefore MWh for the
    hourly dispatch interval). The unit-commitment model does not need to know
    whether the asset is PV, CSP, wind, a generator, or another source.
    ``can_supply_load`` describes its dispatch role; an asset that cannot
    supply load directly may still charge compatible storage assets.
    """

    name: str
    site: object
    power_timeseries: Sequence[float]
    energy_type: str = "electric"
    can_supply_load: bool = True
    can_export: bool = True
    power_priority_load_MW: float | None = None
    off_grid_operation: bool = True
    capex: float | None = None
    opex: float | None = None
    land_area: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Generation.name must be non-empty.")
        if len(self.power_timeseries) == 0:
            raise ValueError(f"{self.name}: power_timeseries must not be empty.")
        if self.power_priority_load_MW is not None and self.power_priority_load_MW < 0:
            raise ValueError(f"{self.name}: power_priority_load_MW must be non-negative.")
