"""Technology-agnostic generation assets used by :mod:`enliten.system`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


def validate_energy_type(value: str, field: str) -> str:
    """Normalize an extensible energy-type label without imposing a fixed enum."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip().lower()


@dataclass
class Generation:
    """An asset with an exogenous time series in one declared energy type.

    ``power_timeseries`` is in MW of ``output_energy_type``. A generation
    asset can directly serve the system load only when its output energy type
    matches ``System.load_energy_type``. Cross-energy conversion belongs in a
    :class:`enliten.storage.ChargingPath`, never in a technology-name branch.
    """

    name: str
    site: object
    power_timeseries: Sequence[float]
    output_energy_type: str = "electric"
    can_supply_load: bool = True
    can_export: bool = True
    power_priority_load_MW: float | None = None
    off_grid_operation: bool = True
    capex: float | None = None
    opex: float | None = None
    variable_opex_USD_per_MWh: float = 0.0
    land_area: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Generation.name must be non-empty.")
        if len(self.power_timeseries) == 0:
            raise ValueError(f"{self.name}: power_timeseries must not be empty.")
        self.output_energy_type = validate_energy_type(
            self.output_energy_type, f"{self.name}.output_energy_type"
        )
        if self.power_priority_load_MW is not None and self.power_priority_load_MW < 0:
            raise ValueError(f"{self.name}: power_priority_load_MW must be non-negative.")
        if self.variable_opex_USD_per_MWh < 0:
            raise ValueError(f"{self.name}: variable_opex_USD_per_MWh must be non-negative.")
