"""Technology-agnostic storage assets and charging-conversion paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .generation import validate_energy_type


NumberOrSeries = float | Sequence[float]


@dataclass(frozen=True)
class ChargingPath:
    """A named conversion path from one generation asset into one store.

    ``maximum_input_rate_MW`` is measured in the generation asset's source
    energy type. ``input_to_stored_efficiency`` converts source MWh to stored
    MWh. This allows, for example, a thermal CSP source to charge a thermal
    store or an electrical battery at different rates and efficiencies.
    """

    generation_name: str
    storage_name: str
    source_energy_type: str
    stored_energy_type: str
    input_to_stored_efficiency: float
    maximum_input_rate_MW: float | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.generation_name or not self.storage_name:
            raise ValueError("ChargingPath generation_name and storage_name must be non-empty.")
        object.__setattr__(
            self, "source_energy_type", validate_energy_type(self.source_energy_type, "source_energy_type")
        )
        object.__setattr__(
            self, "stored_energy_type", validate_energy_type(self.stored_energy_type, "stored_energy_type")
        )
        if not 0 < self.input_to_stored_efficiency <= 1:
            raise ValueError("ChargingPath input_to_stored_efficiency must be in (0, 1].")
        if self.maximum_input_rate_MW is not None and self.maximum_input_rate_MW < 0:
            raise ValueError("ChargingPath maximum_input_rate_MW must be non-negative.")


@dataclass
class Storage:
    """A store whose state of charge is tracked in ``stored_energy_type``.

    ``power_rating_MW`` is the maximum power delivered in
    ``load_output_energy_type``. ``discharge_efficiency`` converts stored MWh
    into that output type and may be a scalar or hourly sequence. An optional
    ``maximum_stored_energy_rate_MW`` caps the aggregate stored-energy added by
    all charging paths in one hour; unlike input rates, it has one consistent
    unit across all paths.
    """

    name: str
    site: object
    capacity_MWh: float
    power_rating_MW: float
    stored_energy_type: str = "electric"
    load_output_energy_type: str = "electric"
    discharge_efficiency: NumberOrSeries = 1.0
    maximum_stored_energy_rate_MW: float | None = None
    minimum_state_of_charge_MWh: float = 0.0
    percent_loss_daily: float = 0.0
    start_full: bool = False
    off_grid_operation: bool = True
    capex: float | None = None
    opex: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Storage.name must be non-empty.")
        self.stored_energy_type = validate_energy_type(
            self.stored_energy_type, f"{self.name}.stored_energy_type"
        )
        self.load_output_energy_type = validate_energy_type(
            self.load_output_energy_type, f"{self.name}.load_output_energy_type"
        )
        if self.capacity_MWh < 0:
            raise ValueError(f"{self.name}: capacity_MWh must be non-negative.")
        if self.power_rating_MW < 0:
            raise ValueError(f"{self.name}: power_rating_MW must be non-negative.")
        if self.maximum_stored_energy_rate_MW is not None and self.maximum_stored_energy_rate_MW < 0:
            raise ValueError(f"{self.name}: maximum_stored_energy_rate_MW must be non-negative.")
        if not 0 <= self.minimum_state_of_charge_MWh <= self.capacity_MWh:
            raise ValueError(
                f"{self.name}: minimum_state_of_charge_MWh must be within capacity_MWh."
            )
        if self.percent_loss_daily < 0:
            raise ValueError(f"{self.name}: percent_loss_daily must be non-negative.")

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
