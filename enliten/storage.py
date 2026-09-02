"""Technology-agnostic storage assets used by :mod:`enliten.system`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


NumberOrSeries = float | Sequence[float]


@dataclass
class Storage:
    """A storage asset with named charging sources and explicit efficiencies.

    ``capacity_MWh`` and state of charge are in the stored-energy unit. The
    discharge efficiency converts stored energy to load-serving energy. It may
    be a scalar or an hourly sequence (for example, a TES thermal-to-electric
    conversion curve). ``power_rating_MW`` limits delivered power, while
    ``charge_rate_MW`` limits input power.

    A capacity is fully dispatchable by default. To retain a reserve, set
    ``minimum_state_of_charge_MWh`` explicitly. This avoids silently
    interpreting a technology label or a percent-DOD field as a dispatch rule.
    """

    name: str
    site: object
    capacity_MWh: float
    power_rating_MW: float
    systems_charging: Sequence[str]
    charge_efficiency: float | Mapping[str, float] = 1.0
    discharge_efficiency: NumberOrSeries = 1.0
    charge_rate_MW: float | None = None
    minimum_state_of_charge_MWh: float = 0.0
    percent_loss_daily: float = 0.0
    start_full: bool = False
    off_grid_operation: bool = True
    capex: float | None = None
    opex: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Storage.name must be non-empty.")
        if self.capacity_MWh < 0:
            raise ValueError(f"{self.name}: capacity_MWh must be non-negative.")
        if self.power_rating_MW < 0:
            raise ValueError(f"{self.name}: power_rating_MW must be non-negative.")
        if self.charge_rate_MW is not None and self.charge_rate_MW < 0:
            raise ValueError(f"{self.name}: charge_rate_MW must be non-negative.")
        if not 0 <= self.minimum_state_of_charge_MWh <= self.capacity_MWh:
            raise ValueError(
                f"{self.name}: minimum_state_of_charge_MWh must be within capacity_MWh."
            )
        if self.percent_loss_daily < 0:
            raise ValueError(f"{self.name}: percent_loss_daily must be non-negative.")
        efficiencies = (
            self.charge_efficiency.values()
            if isinstance(self.charge_efficiency, Mapping)
            else [self.charge_efficiency]
        )
        if any(value <= 0 or value > 1 for value in efficiencies):
            raise ValueError(f"{self.name}: charge efficiency must be in (0, 1].")

    def charge_efficiency_for(self, generation_name: str) -> float:
        if isinstance(self.charge_efficiency, Mapping):
            try:
                return self.charge_efficiency[generation_name]
            except KeyError as exc:
                raise ValueError(
                    f"{self.name}: no charge efficiency configured for {generation_name!r}."
                ) from exc
        return self.charge_efficiency

    def discharge_efficiency_at(self, hour: int) -> float:
        efficiency = self.discharge_efficiency
        if isinstance(efficiency, (str, bytes)):
            raise TypeError(f"{self.name}: discharge_efficiency must be numeric or a sequence.")
        if isinstance(efficiency, Sequence):
            if not efficiency:
                raise ValueError(f"{self.name}: discharge_efficiency sequence must not be empty.")
            value = float(efficiency[hour % len(efficiency)])
        else:
            value = float(efficiency)
        if value <= 0 or value > 1:
            raise ValueError(f"{self.name}: discharge efficiency must be in (0, 1].")
        return value
