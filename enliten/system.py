"""Technology-agnostic hourly unit commitment with explicit energy pathways."""

from __future__ import annotations

from itertools import cycle, islice
import re
from typing import Iterable, Sequence

import pandas as pd

from .generation import Generation, validate_energy_type
from .storage import ChargingPath, Storage


def _site_name(asset: object) -> str:
    site = getattr(asset, "site")
    return getattr(site, "name", str(site))


def _poi_limit(asset: object) -> float | None:
    return getattr(getattr(asset, "site"), "POI_limit", None)


def _token(energy_type: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", energy_type.lower()).strip("_")


class System:
    """Dispatch typed energy flows without checking technology names.

    A :class:`ChargingPath` is the sole way to convert energy while charging.
    Its source and stored-energy labels must match the connected generator and
    storage. Asset order sets storage-discharge priority; ``ChargingPath``
    priority sets charging priority for one generation asset.
    """

    def __init__(
        self,
        load_MW: pd.Series | pd.DataFrame,
        systems_load_order: Iterable[object],
        charging_paths: Sequence[ChargingPath] = (),
        load_energy_type: str = "electric",
    ):
        self.load_MW = self._load_series(load_MW)
        self.load_energy_type = validate_energy_type(load_energy_type, "load_energy_type")
        self.systems = list(systems_load_order)
        self.generators = [asset for asset in self.systems if isinstance(asset, Generation)]
        self.storage_systems = [asset for asset in self.systems if isinstance(asset, Storage)]
        self.charging_paths = list(charging_paths)
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
        self._generators_by_name = {generator.name: generator for generator in self.generators}
        self._storage_by_name = {storage.name: storage for storage in self.storage_systems}
        self._paths_by_generation: dict[str, list[ChargingPath]] = {
            generator.name: [] for generator in self.generators
        }
        seen_connections: set[tuple[str, str]] = set()
        for path in self.charging_paths:
            if path.generation_name not in self._generators_by_name:
                raise ValueError(f"ChargingPath source is not in this system: {path.generation_name!r}")
            if path.storage_name not in self._storage_by_name:
                raise ValueError(f"ChargingPath storage is not in this system: {path.storage_name!r}")
            connection = (path.generation_name, path.storage_name)
            if connection in seen_connections:
                raise ValueError(f"Duplicate ChargingPath for {path.generation_name} -> {path.storage_name}.")
            seen_connections.add(connection)
            generator = self._generators_by_name[path.generation_name]
            storage = self._storage_by_name[path.storage_name]
            if path.source_energy_type != generator.output_energy_type:
                raise ValueError(
                    f"{path.generation_name} -> {path.storage_name}: source_energy_type "
                    f"({path.source_energy_type}) must match generation output "
                    f"({generator.output_energy_type})."
                )
            if path.stored_energy_type != storage.stored_energy_type:
                raise ValueError(
                    f"{path.generation_name} -> {path.storage_name}: stored_energy_type "
                    f"({path.stored_energy_type}) must match storage type "
                    f"({storage.stored_energy_type})."
                )
            self._paths_by_generation[path.generation_name].append(path)
        for paths in self._paths_by_generation.values():
            paths.sort(key=lambda path: path.priority)
        for generator in self.generators:
            if generator.can_supply_load and generator.output_energy_type != self.load_energy_type:
                raise ValueError(
                    f"{generator.name}: {generator.output_energy_type} generation cannot directly serve "
                    f"{self.load_energy_type} load. Set can_supply_load=False or model a conversion path."
                )
            if generator.can_export and generator.output_energy_type != self.load_energy_type:
                raise ValueError(
                    f"{generator.name}: only {self.load_energy_type} generation can export through this "
                    "system's load/grid connection. Set can_export=False."
                )

    @staticmethod
    def _matched_timeseries(values: Iterable[float], length: int) -> list[float]:
        values = list(values)
        return values[:length] if len(values) >= length else list(islice(cycle(values), length))

    def _initial_frame(self) -> pd.DataFrame:
        load_type = _token(self.load_energy_type)
        df = pd.DataFrame({"load_MW": self.load_MW})
        df[f"grid_to_load_MWh_{load_type}"] = 0.0
        df[f"unmet_load_MWh_{load_type}"] = 0.0
        df[f"export_energy_MWh_{load_type}"] = 0.0
        for generator in self.generators:
            source_type = _token(generator.output_energy_type)
            df[f"{generator.name}_available_MW_{source_type}"] = self._matched_timeseries(
                generator.power_timeseries, len(df)
            )
            df[f"{generator.name}_to_load_MWh_{load_type}"] = 0.0
            df[f"{generator.name}_to_grid_MWh_{load_type}"] = 0.0
            df[f"{generator.name}_curtailed_MWh_{source_type}"] = 0.0
        for path in self.charging_paths:
            source_type = _token(path.source_energy_type)
            stored_type = _token(path.stored_energy_type)
            base = f"{path.generation_name}_to_{path.storage_name}"
            df[f"{base}_MWh_{source_type}"] = 0.0
            df[f"{base}_stored_MWh_{stored_type}"] = 0.0
        for storage in self.storage_systems:
            stored_type = _token(storage.stored_energy_type)
            output_type = _token(storage.load_output_energy_type)
            df[f"{storage.name}_MWh_{stored_type}"] = (
                float(storage.capacity_MWh) if storage.start_full else 0.0
            )
            df[f"{storage.name}_to_load_MWh_{output_type}"] = 0.0
            df[f"{storage.name}_loss_MWh_{stored_type}"] = 0.0
        sites = {_site_name(asset): asset.site for asset in self.systems}
        for site in sites.values():
            df[f"{site.name}_POI_MW_{load_type}"] = 0.0
        return df

    @staticmethod
    def _remaining_poi(asset: object, site_dispatch: dict[str, float]) -> float:
        limit = _poi_limit(asset)
        return float("inf") if limit is None else max(0.0, limit - site_dispatch[_site_name(asset)])

    def operation(self) -> pd.DataFrame:
        """Run one-hour dispatch while retaining source, stored, and load types."""
        df = self._initial_frame()
        load_type = _token(self.load_energy_type)
        states = {
            storage.name: float(df.iloc[0][f"{storage.name}_MWh_{_token(storage.stored_energy_type)}"])
            for storage in self.storage_systems
        }

        # Row zero records initial state, matching the legacy package's time convention.
        for position in range(1, len(df)):
            index = df.index[position]
            site_dispatch = {_site_name(asset): 0.0 for asset in self.systems}
            available = {
                generator.name: max(
                    0.0,
                    float(df.loc[index, f"{generator.name}_available_MW_{_token(generator.output_energy_type)}"]),
                )
                for generator in self.generators
            }
            stored_charge_used = {storage.name: 0.0 for storage in self.storage_systems}

            for storage in self.storage_systems:
                stored_type = _token(storage.stored_energy_type)
                loss = states[storage.name] * storage.percent_loss_daily / 2400.0
                states[storage.name] = max(0.0, states[storage.name] - loss)
                df.loc[index, f"{storage.name}_loss_MWh_{stored_type}"] = loss

            unmet = float(df.loc[index, "load_MW"])

            def charge(generator: Generation) -> None:
                for path in self._paths_by_generation[generator.name]:
                    if available[generator.name] <= 0:
                        break
                    storage = self._storage_by_name[path.storage_name]
                    headroom = max(0.0, storage.capacity_MWh - states[storage.name])
                    stored_rate_remaining = (
                        float("inf")
                        if storage.maximum_stored_energy_rate_MW is None
                        else max(0.0, storage.maximum_stored_energy_rate_MW - stored_charge_used[storage.name])
                    )
                    input_rate = (
                        float("inf")
                        if path.maximum_input_rate_MW is None
                        else path.maximum_input_rate_MW
                    )
                    input_energy = max(
                        0.0,
                        min(
                            available[generator.name],
                            input_rate,
                            headroom / path.input_to_stored_efficiency,
                            stored_rate_remaining / path.input_to_stored_efficiency,
                        ),
                    )
                    stored_energy = input_energy * path.input_to_stored_efficiency
                    available[generator.name] -= input_energy
                    states[storage.name] += stored_energy
                    stored_charge_used[storage.name] += stored_energy
                    base = f"{path.generation_name}_to_{path.storage_name}"
                    df.loc[index, f"{base}_MWh_{_token(path.source_energy_type)}"] += input_energy
                    df.loc[index, f"{base}_stored_MWh_{_token(path.stored_energy_type)}"] += stored_energy

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
                delivered = max(
                    0.0,
                    min(
                        available[generator.name],
                        unmet,
                        self._remaining_poi(generator, site_dispatch),
                        direct_limit,
                    ),
                )
                available[generator.name] -= delivered
                unmet -= delivered
                site_dispatch[_site_name(generator)] += delivered
                df.loc[index, f"{generator.name}_to_load_MWh_{load_type}"] = delivered
                charge(generator)

            for storage in self.storage_systems:
                if storage.load_output_energy_type != self.load_energy_type:
                    continue
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
                df.loc[index, f"{storage.name}_to_load_MWh_{load_type}"] = delivered

            for generator in self.generators:
                source_type = _token(generator.output_energy_type)
                if not generator.can_export:
                    df.loc[index, f"{generator.name}_curtailed_MWh_{source_type}"] = available[generator.name]
                    continue
                exported = max(
                    0.0,
                    min(available[generator.name], self._remaining_poi(generator, site_dispatch)),
                )
                available[generator.name] -= exported
                site_dispatch[_site_name(generator)] += exported
                df.loc[index, f"{generator.name}_to_grid_MWh_{load_type}"] = exported
                df.loc[index, f"{generator.name}_curtailed_MWh_{source_type}"] = available[generator.name]

            for storage in self.storage_systems:
                df.loc[index, f"{storage.name}_MWh_{_token(storage.stored_energy_type)}"] = states[storage.name]
            df.loc[index, f"grid_to_load_MWh_{load_type}"] = unmet
            df.loc[index, f"unmet_load_MWh_{load_type}"] = unmet
            df.loc[index, f"export_energy_MWh_{load_type}"] = sum(
                df.loc[index, f"{generator.name}_to_grid_MWh_{load_type}"]
                for generator in self.generators
            )
            for site_name, dispatched in site_dispatch.items():
                df.loc[index, f"{site_name}_POI_MW_{load_type}"] = dispatched
        return df
