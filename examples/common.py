"""Shared deterministic input data for the unit-commitment examples."""

from __future__ import annotations

from itertools import islice, cycle

import pandas as pd

from enliten import Generation, Site, Storage, System


def _repeat(values: list[float], hours: int = 24) -> list[float]:
    return list(islice(cycle(values), hours))


def load_profile(hours: int = 24) -> pd.Series:
    load = pd.Series(_repeat([5.0, 6.0, 7.0, 4.0], hours), name="load_MW")
    load.index.name = "time"
    return load


def pv_bes_system(hours: int = 24) -> System:
    site = Site("example_site")
    pv = Generation("pv", site, _repeat([0.0, 8.0, 10.0, 0.0], hours))
    bes = Storage(
        "bes",
        site,
        capacity_MWh=10.0,
        power_rating_MW=5.0,
        systems_charging=["pv"],
        charge_efficiency={"pv": 0.90},
        discharge_efficiency=0.90,
        charge_rate_MW=5.0,
        start_full=False,
    )
    return System(load_profile(hours), [bes, pv])


def csp_tes_system(hours: int = 24) -> System:
    site = Site("example_site")
    csp = Generation(
        "csp",
        site,
        _repeat([6.0, 8.0, 0.0, 4.0], hours),
        energy_type="thermal",
        can_supply_load=False,
        can_export=False,
    )
    tes = Storage(
        "tes",
        site,
        capacity_MWh=20.0,
        power_rating_MW=5.0,
        systems_charging=["csp"],
        charge_efficiency={"csp": 0.90},
        discharge_efficiency=0.50,
        charge_rate_MW=8.0,
        start_full=False,
    )
    return System(load_profile(hours), [tes, csp])


def pv_csp_bes_tes_system(hours: int = 24) -> System:
    site = Site("example_site")
    csp = Generation(
        "csp",
        site,
        _repeat([6.0, 8.0, 0.0, 4.0], hours),
        energy_type="thermal",
        can_supply_load=False,
        can_export=False,
    )
    pv = Generation("pv", site, _repeat([0.0, 8.0, 10.0, 0.0], hours))
    tes = Storage(
        "tes",
        site,
        capacity_MWh=20.0,
        power_rating_MW=5.0,
        systems_charging=["csp"],
        charge_efficiency={"csp": 0.90},
        discharge_efficiency=0.50,
        charge_rate_MW=8.0,
        start_full=False,
    )
    bes = Storage(
        "bes",
        site,
        capacity_MWh=10.0,
        power_rating_MW=5.0,
        systems_charging=["pv"],
        charge_efficiency={"pv": 0.90},
        discharge_efficiency=0.90,
        charge_rate_MW=5.0,
        start_full=False,
    )
    # Storage order is the load-serving priority: TES then BES. It is an
    # explicit policy, not a technology-specific branch in System.
    return System(load_profile(hours), [tes, csp, bes, pv])


def show(system: System) -> None:
    """Print a compact audit of a scenario."""
    df = system.timeseries
    flow_columns = [column for column in df if "_to_" in column or column == "grid_to_load_MWh"]
    print(df[flow_columns].sum().round(4).to_string())
    print("\nFirst six hours")
    print(df.head(6).round(4).to_string())
