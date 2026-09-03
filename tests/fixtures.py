"""Deterministic fixtures used only by unit tests."""

from itertools import cycle, islice

import pandas as pd

from enliten import ChargingPath, Generation, Site, Storage, System


def _repeat(values: list[float], hours: int) -> list[float]:
    return list(islice(cycle(values), hours))


def fixture_pv_bes_system(hours: int = 24) -> System:
    site = Site("fixture_site")
    pv = Generation("pv", site, _repeat([0.0, 8.0, 10.0, 0.0], hours), "electric")
    bes = Storage("bes", site, 10.0, 5.0, "electric", "electric", 0.90, start_full=False)
    paths = [ChargingPath("pv", "bes", "electric", "electric", 0.90, 5.0)]
    return System(pd.Series(_repeat([5.0, 6.0, 7.0, 4.0], hours), name="load_MW"), [bes, pv], paths)


def fixture_csp_tes_system(hours: int = 24) -> System:
    site = Site("fixture_site")
    csp = Generation("csp", site, _repeat([6.0, 8.0, 0.0, 4.0], hours), "thermal", False, False)
    tes = Storage("tes", site, 20.0, 5.0, "thermal", "electric", 0.50, start_full=False)
    paths = [ChargingPath("csp", "tes", "thermal", "thermal", 0.90, 8.0)]
    return System(pd.Series(_repeat([5.0, 6.0, 7.0, 4.0], hours), name="load_MW"), [tes, csp], paths)


def fixture_pv_csp_bes_tes_system(hours: int = 24) -> System:
    site = Site("fixture_site")
    csp = Generation("csp", site, _repeat([6.0, 8.0, 0.0, 4.0], hours), "thermal", False, False)
    pv = Generation("pv", site, _repeat([0.0, 8.0, 10.0, 0.0], hours), "electric")
    tes = Storage("tes", site, 20.0, 5.0, "thermal", "electric", 0.50, start_full=False)
    bes = Storage("bes", site, 10.0, 5.0, "electric", "electric", 0.90, start_full=False)
    paths = [
        ChargingPath("csp", "tes", "thermal", "thermal", 0.90, 8.0),
        ChargingPath("pv", "bes", "electric", "electric", 0.90, 5.0),
    ]
    return System(pd.Series(_repeat([5.0, 6.0, 7.0, 4.0], hours), name="load_MW"), [tes, csp, bes, pv], paths)


def fixture_csp_multiple_storage_system() -> System:
    site = Site("fixture_site")
    csp = Generation("csp", site, [0.0, 10.0, 0.0], "thermal", False, False)
    tes = Storage("tes", site, 10.0, 5.0, "thermal", "electric", 0.50)
    bes = Storage("bes", site, 10.0, 5.0, "electric", "electric", 0.90)
    paths = [
        ChargingPath("csp", "tes", "thermal", "thermal", 0.90, 6.0, priority=0),
        ChargingPath("csp", "bes", "thermal", "electric", 0.40, 10.0, priority=1),
    ]
    return System(pd.Series([0.0, 0.0, 0.0], name="load_MW"), [tes, bes, csp], paths)
