"""Technology-agnostic unit commitment, metrics, resilience, and plotting."""

from __future__ import annotations

from copy import deepcopy
from itertools import cycle, islice
from numbers import Real
import random
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
    """Dispatch typed energy flows and expose normal and off-grid metrics.

    ``ChargingPath`` is the only conversion mechanism: its energy labels and
    efficiency are validated against the connected assets. ``grid_available``
    separates normal operation (remaining load is supplied by grid) from an
    off-grid case (remaining load is unmet).
    """

    def __init__(
        self,
        load_MW: pd.Series | pd.DataFrame,
        systems_load_order: Iterable[object],
        charging_paths: Sequence[ChargingPath] = (),
        load_energy_type: str = "electric",
        grid_available: bool = True,
        electricity_sale_USD_per_kWh: float = 0.0,
        grid_energy_cost_USD_per_kWh: float = 0.0,
    ):
        self.load_MW = self._load_series(load_MW)
        self.load_energy_type = validate_energy_type(load_energy_type, "load_energy_type")
        self.grid_available = grid_available
        self.electricity_sale_USD_per_kWh = electricity_sale_USD_per_kWh
        self.grid_energy_cost_USD_per_kWh = grid_energy_cost_USD_per_kWh
        self.systems = list(systems_load_order)
        self.generators = [asset for asset in self.systems if isinstance(asset, Generation)]
        self.storage_systems = [asset for asset in self.systems if isinstance(asset, Storage)]
        self.charging_paths = list(charging_paths)
        if electricity_sale_USD_per_kWh < 0 or grid_energy_cost_USD_per_kWh < 0:
            raise ValueError("Electricity sale and grid-energy cost rates must be non-negative.")
        if len(self.generators) + len(self.storage_systems) != len(self.systems):
            unknown = [
                type(asset).__name__ for asset in self.systems if not isinstance(asset, (Generation, Storage))
            ]
            raise TypeError(f"System assets must be Generation or Storage; received {unknown}.")
        self._validate_assets()
        self.timeseries = self.operation()
        self.metrics = self.system_metrics()

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
            initial_energy = (
                storage.initial_energy_MWh
                if storage.initial_energy_MWh is not None
                else storage.capacity_MWh if storage.start_full else 0.0
            )
            df[f"{storage.name}_MWh_{stored_type}"] = float(initial_energy)
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
                    input_rate = float("inf") if path.maximum_input_rate_MW is None else path.maximum_input_rate_MW
                    input_energy = max(
                        0.0,
                        min(
                            available[generator.name], input_rate,
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
                direct_limit = float("inf") if generator.power_priority_load_MW is None else generator.power_priority_load_MW
                delivered = max(
                    0.0,
                    min(available[generator.name], unmet, self._remaining_poi(generator, site_dispatch), direct_limit),
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
                available_energy = max(0.0, states[storage.name] - storage.minimum_state_of_charge_MWh)
                delivered = max(
                    0.0,
                    min(unmet, storage.power_rating_MW, available_energy * efficiency, self._remaining_poi(storage, site_dispatch)),
                )
                states[storage.name] -= delivered / efficiency
                unmet -= delivered
                site_dispatch[_site_name(storage)] += delivered
                df.loc[index, f"{storage.name}_to_load_MWh_{load_type}"] = delivered
            for generator in self.generators:
                source_type = _token(generator.output_energy_type)
                # An isolated microgrid has no external point of delivery;
                # residual production is curtailed rather than reported as a
                # fictitious grid export.
                if not self.grid_available or not generator.can_export:
                    df.loc[index, f"{generator.name}_curtailed_MWh_{source_type}"] = available[generator.name]
                    continue
                exported = max(0.0, min(available[generator.name], self._remaining_poi(generator, site_dispatch)))
                available[generator.name] -= exported
                site_dispatch[_site_name(generator)] += exported
                df.loc[index, f"{generator.name}_to_grid_MWh_{load_type}"] = exported
                df.loc[index, f"{generator.name}_curtailed_MWh_{source_type}"] = available[generator.name]
            for storage in self.storage_systems:
                df.loc[index, f"{storage.name}_MWh_{_token(storage.stored_energy_type)}"] = states[storage.name]
            df.loc[index, f"grid_to_load_MWh_{load_type}"] = unmet if self.grid_available else 0.0
            df.loc[index, f"unmet_load_MWh_{load_type}"] = 0.0 if self.grid_available else unmet
            df.loc[index, f"export_energy_MWh_{load_type}"] = sum(
                df.loc[index, f"{generator.name}_to_grid_MWh_{load_type}"] for generator in self.generators
            )
            for site_name, dispatched in site_dispatch.items():
                df.loc[index, f"{site_name}_POI_MW_{load_type}"] = dispatched
        return df

    def _operating_rows(self) -> pd.DataFrame:
        return self.timeseries.iloc[1:].copy() if len(self.timeseries) > 1 else self.timeseries.copy()

    def _annual_values(self, series: pd.Series) -> list[float]:
        if isinstance(series.index, pd.DatetimeIndex):
            return [float(value) for value in series.groupby(series.index.year).sum().tolist()]
        hours = max(len(series), 1)
        return [float(series.sum() * 8760.0 / hours)]

    def system_metrics(self) -> dict[str, object]:
        """Compute normal-operation metrics, including TEA-ready annual inputs."""
        df = self._operating_rows()
        load_type = _token(self.load_energy_type)
        grid_col = f"grid_to_load_MWh_{load_type}"
        unmet_col = f"unmet_load_MWh_{load_type}"
        export_col = f"export_energy_MWh_{load_type}"
        generator_load_cols = [f"{asset.name}_to_load_MWh_{load_type}" for asset in self.generators]
        storage_load_cols = [
            f"{asset.name}_to_load_MWh_{load_type}"
            for asset in self.storage_systems
            if asset.load_output_energy_type == self.load_energy_type
        ]
        generator_load = df[generator_load_cols].sum(axis=1) if generator_load_cols else pd.Series(0.0, index=df.index)
        storage_load = df[storage_load_cols].sum(axis=1) if storage_load_cols else pd.Series(0.0, index=df.index)
        system_load = generator_load + storage_load
        load = df["load_MW"]
        metrics: dict[str, object] = {
            "operating_hours": int(len(df)),
            "load_MWh_electric": float(load.sum()),
            "generation_to_load_MWh_electric": float(generator_load.sum()),
            "storage_to_load_MWh_electric": float(storage_load.sum()),
            "system_to_load_MWh_electric": float(system_load.sum()),
            "grid_to_load_MWh_electric": float(df[grid_col].sum()),
            "unmet_load_MWh_electric": float(df[unmet_col].sum()),
            "export_energy_MWh_electric": float(df[export_col].sum()),
            "percent_load_met": 100.0 * float(system_load.sum() + df[grid_col].sum()) / float(load.sum()) if load.sum() else 100.0,
            "percent_load_by_system": 100.0 * float(system_load.sum()) / float(load.sum()) if load.sum() else 100.0,
            "system_capex_USD": float(sum(asset.capex or 0.0 for asset in self.systems)),
            "system_annual_OM_USD": float(sum(asset.opex or 0.0 for asset in self.systems)),
        }
        for generator in self.generators:
            source = _token(generator.output_energy_type)
            metrics[f"{generator.name}_curtailed_MWh_{source}"] = float(
                df[f"{generator.name}_curtailed_MWh_{source}"].sum()
            )
        metrics["load_annual_MWh_electric"] = self._annual_values(load)
        metrics["system_to_load_annual_MWh_electric"] = self._annual_values(system_load)
        metrics["grid_to_load_annual_MWh_electric"] = self._annual_values(df[grid_col])
        metrics["export_energy_annual_MWh_electric"] = self._annual_values(df[export_col])
        metrics["annual_electricity_sales_USD"] = [
            value * 1000.0 * self.electricity_sale_USD_per_kWh
            for value in metrics["export_energy_annual_MWh_electric"]
        ]
        metrics["annual_electricity_purchases_USD"] = [
            value * 1000.0 * self.grid_energy_cost_USD_per_kWh
            for value in metrics["grid_to_load_annual_MWh_electric"]
        ]
        variable_om = 0.0
        for generator in self.generators:
            output = (
                df[f"{generator.name}_to_load_MWh_{load_type}"]
                + df[f"{generator.name}_to_grid_MWh_{load_type}"]
            ).sum()
            for path in self._paths_by_generation[generator.name]:
                output += df[f"{path.generation_name}_to_{path.storage_name}_MWh_{_token(path.source_energy_type)}"].sum()
            variable_om += output * generator.variable_opex_USD_per_MWh
        for storage in self.storage_systems:
            output_column = f"{storage.name}_to_load_MWh_{load_type}"
            if output_column in df:
                variable_om += df[output_column].sum() * storage.variable_opex_USD_per_MWh
        factor = 8760.0 / max(len(df), 1)
        metrics["system_annual_VOM_USD"] = float(variable_om * factor)
        metrics["system_augment_USD"] = [0.0] * len(metrics["system_to_load_annual_MWh_electric"])
        # Compatibility alias for the former TEA calculator.
        metrics["system_augment"] = metrics["system_augment_USD"]
        return metrics

    def tea_metrics(self) -> dict[str, object]:
        """Return the normal-operation fields commonly consumed by a TEA model."""
        return self.system_metrics()

    def _wrapped_positions(self, start_hour: int, length: int) -> list[int]:
        if not 0 <= start_hour < len(self.timeseries):
            raise ValueError(f"start_hour must be between 0 and {len(self.timeseries) - 1}.")
        return [(start_hour + offset) % len(self.timeseries) for offset in range(length)]

    def _critical_load_profile(self, critical_load_MW: Real | Sequence[float], length: int) -> pd.Series:
        if isinstance(critical_load_MW, Real):
            values = [float(critical_load_MW)] * length
        else:
            values = self._matched_timeseries(critical_load_MW, length)
        return pd.Series(values, name="load_MW")

    def _off_grid_case(
        self, start_hour: int, critical_load_MW: Real | Sequence[float], target_hours: int, initial_state: str
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        positions = self._wrapped_positions(start_hour, target_hours + 1)
        assets = [deepcopy(asset) for asset in self.systems if asset.off_grid_operation]
        names = {asset.name for asset in assets}
        for asset in assets:
            if isinstance(asset, Generation):
                source = f"{asset.name}_available_MW_{_token(asset.output_energy_type)}"
                asset.power_timeseries = self.timeseries.iloc[positions][source].tolist()
            else:
                state_col = f"{asset.name}_MWh_{_token(asset.stored_energy_type)}"
                if initial_state == "actual":
                    asset.initial_energy_MWh = float(self.timeseries.iloc[start_hour][state_col])
                elif initial_state == "full":
                    asset.initial_energy_MWh = asset.capacity_MWh
                else:
                    raise ValueError("initial_state must be 'actual' or 'full'.")
        paths = [
            path for path in self.charging_paths if path.generation_name in names and path.storage_name in names
        ]
        case = System(
            self._critical_load_profile(critical_load_MW, target_hours + 1), assets, paths,
            self.load_energy_type, grid_available=False,
            electricity_sale_USD_per_kWh=self.electricity_sale_USD_per_kWh,
            grid_energy_cost_USD_per_kWh=self.grid_energy_cost_USD_per_kWh,
        )
        result = case.timeseries.iloc[1:]
        unmet = result[f"unmet_load_MWh_{_token(self.load_energy_type)}"]
        failed = unmet.gt(1e-9)
        # Duration is the number of completely served hours before the first
        # shortage, not the dataframe label of that shortage.
        failure_positions = [i for i, value in enumerate(failed.to_list()) if value]
        duration = failure_positions[0] if failure_positions else target_hours
        total_load = float(result["load_MW"].sum())
        unmet_energy = float(unmet.sum())
        summary = {
            "duration_hours": duration,
            "reaches_target": duration >= target_hours,
            "pct_target_energy_served": 1.0 if total_load == 0 else 1.0 - unmet_energy / total_load,
            "unmet_target_energy_MWh_electric": unmet_energy,
        }
        return case.timeseries, summary

    def resilience_cases(
        self,
        critical_load_MW: Real | Sequence[float],
        target_hours: int,
        n_starts: int = 10,
        seed: int | None = None,
        start_hours: Sequence[int] | None = None,
    ) -> pd.DataFrame:
        """Run random-start, off-grid cases for actual and fully charged stores.

        Supply ``seed`` for reproducible random starts or ``start_hours`` for
        exact starts. Results are retained on ``resilience_results`` and their
        summary metrics on ``resilience_summary``.
        """
        if not isinstance(target_hours, int) or isinstance(target_hours, bool) or target_hours <= 0:
            raise ValueError("target_hours must be a positive integer.")
        if start_hours is None:
            if not isinstance(n_starts, int) or isinstance(n_starts, bool) or n_starts <= 0:
                raise ValueError("n_starts must be a positive integer.")
            rng = random.Random(seed)
            starts = [rng.randrange(len(self.timeseries)) for _ in range(n_starts)]
        else:
            starts = list(start_hours)
            if not starts:
                raise ValueError("start_hours must not be empty.")
        rows = []
        for start in starts:
            _, actual = self._off_grid_case(start, critical_load_MW, target_hours, "actual")
            _, full = self._off_grid_case(start, critical_load_MW, target_hours, "full")
            rows.append({
                "start_hour": start,
                "actual_duration_hours": actual["duration_hours"],
                "full_duration_hours": full["duration_hours"],
                "actual_reaches_target": actual["reaches_target"],
                "full_reaches_target": full["reaches_target"],
                # These aliases preserve the column names returned by the
                # former resilience helper.  Here "to_end" means the stated
                # resilience target is reached, rather than an opaque index.
                "to_end_actual": actual["reaches_target"],
                "to_end_full": full["reaches_target"],
                "pct_target_energy_actual": actual["pct_target_energy_served"],
                "pct_target_energy_full": full["pct_target_energy_served"],
                "target_energy_actual_MWh_electric": actual["unmet_target_energy_MWh_electric"],
                "target_energy_full_MWh_electric": full["unmet_target_energy_MWh_electric"],
                "target_energy_actual": actual["unmet_target_energy_MWh_electric"],
                "target_energy_full": full["unmet_target_energy_MWh_electric"],
            })
        self.resilience_results = pd.DataFrame(rows)
        self.resilience_summary = self.resilience_metrics(self.resilience_results, target_hours)
        return self.resilience_results

    @staticmethod
    def resilience_metrics(cases: pd.DataFrame, target_hours: int) -> dict[str, float | int]:
        """Summarize durations and target-energy service across resilience cases."""
        if cases.empty:
            raise ValueError("Resilience cases must not be empty.")
        results: dict[str, float | int] = {
            "n_starts": len(cases),
            "pct_meets_actual": 100.0 * float(cases["actual_reaches_target"].mean()),
            "pct_meets_full": 100.0 * float(cases["full_reaches_target"].mean()),
            "actual_reaches_end_pct": 100.0 * float((cases["actual_duration_hours"] >= target_hours).mean()),
            "full_reaches_end_pct": 100.0 * float((cases["full_duration_hours"] >= target_hours).mean()),
        }
        for state in ("actual", "full"):
            duration = cases[f"{state}_duration_hours"]
            energy = cases[f"target_energy_{state}_MWh_electric"]
            served = cases[f"pct_target_energy_{state}"]
            for percentile, label in ((0.1, "tenth"), (0.5, "fiftieth"), (0.9, "ninetieth")):
                results[f"{label}_pctile_{state}_hrs"] = float(duration.quantile(percentile))
                results[f"{label}_pctile_target_energy_{state}_MWh_electric"] = float(energy.quantile(percentile))
                results[f"{label}_pctile_target_energy_{state}"] = results[
                    f"{label}_pctile_target_energy_{state}_MWh_electric"
                ]
                results[f"{label}_pctile_pct_target_energy_{state}"] = 100.0 * float(served.quantile(percentile))
            results[f"pct_meets_target_energy_{state}"] = 100.0 * float((served >= 1.0 - 1e-9).mean())
        return results

    def _plot_window(self, start_date: object, days: int, seed: int | None = None) -> pd.DataFrame:
        if days <= 0:
            raise ValueError("days must be positive.")
        rows = min(len(self.timeseries), days * 24)
        if start_date == "random":
            start = random.Random(seed).randrange(max(1, len(self.timeseries) - rows + 1))
        elif isinstance(start_date, int):
            start = start_date
        elif isinstance(self.timeseries.index, pd.DatetimeIndex):
            locations = self.timeseries.index.get_indexer([pd.Timestamp(start_date)])
            if locations[0] < 0:
                raise ValueError(f"start_date {start_date!r} is not in the time series index.")
            start = int(locations[0])
        else:
            raise TypeError("Use an integer start position or 'random' for a non-datetime index.")
        return self.timeseries.iloc[start : start + rows].copy()

    def timeseries_plot_source(
        self, start_date: object = "random", days: int = 7, type: str = "area",
        color_seq: Sequence[str] | None = None, system_seq: Sequence[str] | None = None, seed: int | None = None,
    ):
        """Plot individual generation/storage/grid contributions to typed load."""
        import matplotlib.pyplot as plt

        df = self._plot_window(start_date, days, seed)
        load_type = _token(self.load_energy_type)
        columns = list(system_seq) if system_seq is not None else [
            *[f"{asset.name}_to_load_MWh_{load_type}" for asset in self.generators],
            *[f"{asset.name}_to_load_MWh_{load_type}" for asset in self.storage_systems],
            f"grid_to_load_MWh_{load_type}",
        ]
        columns = [column for column in columns if column in df and df[column].any()]
        fig, ax = plt.subplots()
        if columns:
            if type == "bar":
                df[columns].plot(kind="bar", stacked=True, width=1, ax=ax, color=color_seq)
            elif type == "area":
                df[columns].plot.area(stacked=True, ax=ax, lw=0, color=color_seq)
            else:
                raise ValueError("type must be 'area' or 'bar'.")
        df["load_MW"].plot(ax=ax, color="black", label="load")
        ax.set_ylabel(f"Hourly Energy (MWh_{self.load_energy_type})")
        ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        return fig, ax

    def timeseries_plot_group(self, start_date: object = "random", days: int = 7, seed: int | None = None):
        """Plot grouped generation, storage, and grid contributions to load."""
        import matplotlib.pyplot as plt

        df = self._plot_window(start_date, days, seed)
        load_type = _token(self.load_energy_type)
        grouped = pd.DataFrame(index=df.index)
        grouped["Generation"] = sum((df[f"{asset.name}_to_load_MWh_{load_type}"] for asset in self.generators), start=0)
        grouped["Storage"] = sum((df[f"{asset.name}_to_load_MWh_{load_type}"] for asset in self.storage_systems), start=0)
        grouped["Grid"] = df[f"grid_to_load_MWh_{load_type}"]
        grouped = grouped.loc[:, grouped.any()]
        fig, ax = plt.subplots()
        grouped.plot.area(stacked=True, ax=ax, lw=0)
        df["load_MW"].plot(ax=ax, color="black", label="load")
        ax.set_ylabel(f"Hourly Energy (MWh_{self.load_energy_type})")
        ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        return fig, ax

    def plot_storage_capacity(self, start_date: object = "random", days: int = 7, seed: int | None = None):
        """Plot each storage asset's typed state of charge."""
        import matplotlib.pyplot as plt

        df = self._plot_window(start_date, days, seed)
        columns = [f"{asset.name}_MWh_{_token(asset.stored_energy_type)}" for asset in self.storage_systems]
        fig, ax = plt.subplots()
        if columns:
            df[columns].plot(ax=ax)
        ax.set_ylabel("Stored Energy (MWh by storage energy type)")
        ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
        return fig, ax
