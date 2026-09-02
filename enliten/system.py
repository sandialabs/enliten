"""Technology-agnostic hourly unit commitment for generation and storage."""

from __future__ import annotations

from itertools import cycle, islice
from typing import Iterable

import pandas as pd

from .generation import Generation
from .storage import Storage


def _site_name(asset: object) -> str:
    site = getattr(asset, "site")
    return getattr(site, "name", str(site))


def _poi_limit(asset: object) -> float | None:
    return getattr(getattr(asset, "site"), "POI_limit", None)


class System:
    """Dispatch generation and storage without technology-specific branches.

    Asset order is meaningful: non-load-serving generators first charge
    compatible storage, load-serving generators then serve load and charge
    storage, and storage is discharged in supplied order. This reproduces the
    legacy CSP->TES, PV->load/charge, BES->load, TES->load priority without
    checking for PV, CSP, BES, or TES classes.
    """

    def __init__(self, load_MW: pd.Series | pd.DataFrame, systems_load_order: Iterable[object]):
        self.load_MW = self._load_series(load_MW)
        self.systems = list(systems_load_order)
        self.generators = [asset for asset in self.systems if isinstance(asset, Generation)]
        self.storage_systems = [asset for asset in self.systems if isinstance(asset, Storage)]
        if len(self.generators) + len(self.storage_systems) != len(self.systems):
            unknown = [
                type(asset).__name__
                for asset in self.systems
                if not isinstance(asset, (Generation, Storage))
            ]
            raise TypeError(f"System assets must be Generation or Storage; received {unknown}.")
        self._validate_assets()
        self.timeseries = self.operation()

    @staticmethod
    def _load_series(load_MW: pd.Series | pd.DataFrame) -> pd.Series:
        if isinstance(load_MW, pd.DataFrame):
            if "load_MW" not in load_MW:
                raise ValueError("load_MW DataFrame must contain a 'load_MW' column.")
            load = load_MW["load_MW"].copy()
        elif isinstance(load_MW, pd.Series):
            load = load_MW.copy()
        else:
            raise TypeError("load_MW must be a pandas Series or DataFrame.")
        if len(load) == 0:
            raise ValueError("load_MW must contain at least one timestep.")
        return load.astype(float).abs().rename("load_MW")

    def _validate_assets(self) -> None:
        names = [asset.name for asset in self.systems]
        if len(names) != len(set(names)):
            raise ValueError("Every generation and storage asset must have a unique name.")
        generator_names = {generator.name for generator in self.generators}
        for storage in self.storage_systems:
            missing = set(storage.systems_charging) - generator_names
            if missing:
                raise ValueError(
                    f"{storage.name}: charging sources are not in this system: {sorted(missing)}"
                )

    @staticmethod
    def _matched_timeseries(values: Iterable[float], length: int) -> list[float]:
        values = list(values)
        return values[:length] if len(values) >= length else list(islice(cycle(values), length))

    def _initial_frame(self) -> pd.DataFrame:
        df = pd.DataFrame({"load_MW": self.load_MW})
        df["grid_to_load_MWh"] = 0.0
        df["unmet_load_MWh"] = 0.0
        df["export_energy_MWh"] = 0.0
        for generator in self.generators:
            df[f"{generator.name}_available_MW"] = self._matched_timeseries(
                generator.power_timeseries, len(df)
            )
            df[f"{generator.name}_to_load_MWh"] = 0.0
            df[f"{generator.name}_to_grid_MWh"] = 0.0
            df[f"{generator.name}_curtailed_MWh"] = 0.0
            for storage in self.storage_systems:
                if generator.name in storage.systems_charging:
                    df[f"{generator.name}_to_{storage.name}_MWh"] = 0.0
        for storage in self.storage_systems:
            df[f"{storage.name}_MWh"] = float(storage.capacity_MWh) if storage.start_full else 0.0
            df[f"{storage.name}_to_load_MWh"] = 0.0
            df[f"{storage.name}_loss_MWh"] = 0.0
        sites = {_site_name(asset): asset.site for asset in self.systems}
        for site in sites.values():
            df[f"{site.name}_POI_MW"] = 0.0
        return df

    @staticmethod
    def _remaining_poi(asset: object, site_dispatch: dict[str, float]) -> float:
        limit = _poi_limit(asset)
        return float("inf") if limit is None else max(0.0, limit - site_dispatch[_site_name(asset)])

    def operation(self) -> pd.DataFrame:
        """Run a one-hour-step dispatch and return auditable named energy flows."""
        df = self._initial_frame()
        states = {
            storage.name: float(df.iloc[0][f"{storage.name}_MWh"])
            for storage in self.storage_systems
        }

        # Row zero records initial state, matching the legacy package's time
        # convention. Dispatch begins at the second timestamp.
        for position in range(1, len(df)):
            index = df.index[position]
            site_dispatch = {_site_name(asset): 0.0 for asset in self.systems}
            available = {
                generator.name: max(0.0, float(df.loc[index, f"{generator.name}_available_MW"]))
                for generator in self.generators
            }
            charge_remaining = {
                storage.name: (
                    storage.charge_rate_MW
                    if storage.charge_rate_MW is not None
                    else float("inf")
                )
                for storage in self.storage_systems
            }

            for storage in self.storage_systems:
                loss = states[storage.name] * storage.percent_loss_daily / 2400.0
                states[storage.name] = max(0.0, states[storage.name] - loss)
                df.loc[index, f"{storage.name}_loss_MWh"] = loss

            unmet = float(df.loc[index, "load_MW"])

            def charge(generator: Generation) -> None:
                for storage in self.storage_systems:
                    if generator.name not in storage.systems_charging or available[generator.name] <= 0:
                        continue
                    efficiency = storage.charge_efficiency_for(generator.name)
                    headroom = max(0.0, storage.capacity_MWh - states[storage.name])
                    amount = max(
                        0.0,
                        min(
                            available[generator.name],
                            charge_remaining[storage.name],
                            headroom / efficiency,
                        ),
                    )
                    available[generator.name] -= amount
                    states[storage.name] += amount * efficiency
                    charge_remaining[storage.name] -= amount
                    df.loc[index, f"{generator.name}_to_{storage.name}_MWh"] += amount

            # Non-load-serving generation (e.g. thermal CSP) charges storage
            # first. No technology name appears in this decision.
            for generator in self.generators:
                if not generator.can_supply_load:
                    charge(generator)

            for generator in self.generators:
                if not generator.can_supply_load:
                    continue
                direct_limit = (
                    float("inf")
                    if generator.power_priority_load_MW is None
                    else generator.power_priority_load_MW
                )
                amount = max(
                    0.0,
                    min(
                        available[generator.name],
                        unmet,
                        self._remaining_poi(generator, site_dispatch),
                        direct_limit,
                    ),
                )
                available[generator.name] -= amount
                unmet -= amount
                site_dispatch[_site_name(generator)] += amount
                df.loc[index, f"{generator.name}_to_load_MWh"] = amount
                charge(generator)

            for storage in self.storage_systems:
                efficiency = storage.discharge_efficiency_at(position - 1)
                available_energy = max(
                    0.0, states[storage.name] - storage.minimum_state_of_charge_MWh
                )
                delivered = max(
                    0.0,
                    min(
                        unmet,
                        storage.power_rating_MW,
                        available_energy * efficiency,
                        self._remaining_poi(storage, site_dispatch),
                    ),
                )
                states[storage.name] -= delivered / efficiency
                unmet -= delivered
                site_dispatch[_site_name(storage)] += delivered
                df.loc[index, f"{storage.name}_to_load_MWh"] = delivered

            for generator in self.generators:
                if not generator.can_export:
                    df.loc[index, f"{generator.name}_curtailed_MWh"] = available[generator.name]
                    continue
                exported = max(
                    0.0,
                    min(available[generator.name], self._remaining_poi(generator, site_dispatch)),
                )
                available[generator.name] -= exported
                site_dispatch[_site_name(generator)] += exported
                df.loc[index, f"{generator.name}_to_grid_MWh"] = exported
                df.loc[index, f"{generator.name}_curtailed_MWh"] = available[generator.name]

            for storage in self.storage_systems:
                df.loc[index, f"{storage.name}_MWh"] = states[storage.name]
            df.loc[index, "grid_to_load_MWh"] = unmet
            df.loc[index, "unmet_load_MWh"] = unmet
            df.loc[index, "export_energy_MWh"] = sum(
                df.loc[index, f"{generator.name}_to_grid_MWh"] for generator in self.generators
            )
            for site_name, dispatched in site_dispatch.items():
                df.loc[index, f"{site_name}_POI_MW"] = dispatched
        return df
