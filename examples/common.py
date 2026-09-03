"""Shared deterministic input data for the unit-commitment examples."""

from __future__ import annotations

from itertools import cycle, islice

import pandas as pd

from enliten import ChargingPath, Generation, Site, Storage, System


def _repeat(values: list[float], hours: int = 24) -> list[float]:
    return list(islice(cycle(values), hours))


def load_profile(hours: int = 24) -> pd.Series:
    load = pd.Series(_repeat([5.0, 6.0, 7.0, 4.0], hours), name="load_MW")
    load.index.name = "time"
    return load


def pv_bes_system(hours: int = 24) -> System:
    site = Site("example_site")
    pv = Generation("pv", site, _repeat([0.0, 8.0, 10.0, 0.0], hours), "electric")
    bes = Storage(
        "bes", site, capacity_MWh=10.0, power_rating_MW=5.0,
        stored_energy_type="electric", load_output_energy_type="electric",
        discharge_efficiency=0.90, start_full=False,
    )
    paths = [ChargingPath("pv", "bes", "electric", "electric", 0.90, 5.0)]
    return System(load_profile(hours), [bes, pv], paths)


def csp_tes_system(hours: int = 24) -> System:
    site = Site("example_site")
    csp = Generation(
        "csp", site, _repeat([6.0, 8.0, 0.0, 4.0], hours), "thermal",
        can_supply_load=False, can_export=False,
    )
    tes = Storage(
        "tes", site, capacity_MWh=20.0, power_rating_MW=5.0,
        stored_energy_type="thermal", load_output_energy_type="electric",
        discharge_efficiency=0.50, start_full=False,
    )
    paths = [ChargingPath("csp", "tes", "thermal", "thermal", 0.90, 8.0)]
    return System(load_profile(hours), [tes, csp], paths)


def pv_csp_bes_tes_system(hours: int = 24) -> System:
    site = Site("example_site")
    csp = Generation(
        "csp", site, _repeat([6.0, 8.0, 0.0, 4.0], hours), "thermal",
        can_supply_load=False, can_export=False,
    )
    pv = Generation("pv", site, _repeat([0.0, 8.0, 10.0, 0.0], hours), "electric")
    tes = Storage(
        "tes", site, capacity_MWh=20.0, power_rating_MW=5.0,
        stored_energy_type="thermal", load_output_energy_type="electric",
        discharge_efficiency=0.50, start_full=False,
    )
    bes = Storage(
        "bes", site, capacity_MWh=10.0, power_rating_MW=5.0,
        stored_energy_type="electric", load_output_energy_type="electric",
        discharge_efficiency=0.90, start_full=False,
    )
    paths = [
        ChargingPath("csp", "tes", "thermal", "thermal", 0.90, 8.0, priority=0),
        ChargingPath("pv", "bes", "electric", "electric", 0.90, 5.0, priority=0),
    ]
    # Storage order is load-serving priority: TES then BES.
    return System(load_profile(hours), [tes, csp, bes, pv], paths)


def csp_multiple_storage_system() -> System:
    """CSP charges TES and BES through separate typed conversion paths."""
    site = Site("example_site")
    csp = Generation("csp", site, [0.0, 10.0, 0.0], "thermal", False, False)
    tes = Storage("tes", site, 10.0, 5.0, "thermal", "electric", 0.50)
    bes = Storage("bes", site, 10.0, 5.0, "electric", "electric", 0.90)
    paths = [
        ChargingPath("csp", "tes", "thermal", "thermal", 0.90, 6.0, priority=0),
        ChargingPath("csp", "bes", "thermal", "electric", 0.40, 10.0, priority=1),
    ]
    load = pd.Series([0.0, 0.0, 0.0], name="load_MW")
    load.index.name = "time"
    return System(load, [tes, bes, csp], paths)


def show(system: System) -> None:
    """Print a compact audit of source, stored, and load-energy flows."""
    df = system.timeseries
    flow_columns = [column for column in df if "_to_" in column or column.startswith("grid_to_")]
    print(df[flow_columns].sum().round(4).to_string())
    print("\nFirst six hours")
    print(df.head(6).round(4).to_string())
