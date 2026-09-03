"""Shared deterministic input data for the unit-commitment examples."""

from __future__ import annotations

from itertools import cycle, islice
from pathlib import Path

import pandas as pd

from enliten import ChargingPath, Generation, Site, Storage, System


DATA_DIRECTORY = Path(__file__).with_name("data")

# Illustrative microgrid sizes for the supplied PNM traces. They were selected
# with representative January and July dispatch checks: the combined system
# has periods of full self-supply in summer while retaining grid dependence in
# lower-resource/high-load periods. They are not a planning recommendation.
DEFAULT_DEMAND_MULTIPLIER = 0.05
DEFAULT_PV_CAPACITY_MULTIPLIER = 2_000.0
DEFAULT_CSP_CAPACITY_MULTIPLIER = 1.0
DEFAULT_BES_CAPACITY_MWH = 750.0
DEFAULT_BES_POWER_MW = 150.0
DEFAULT_TES_CAPACITY_MWH_THERMAL = 2_500.0
DEFAULT_TES_POWER_MW_ELECTRIC = 150.0
DEFAULT_TES_MAX_CHARGE_MW_THERMAL = 300.0
MULTI_STORAGE_TES_MAX_INPUT_MW_THERMAL = 200.0

# Illustrative 2022-real-dollar cost assumptions.  PV and CSP+TES are drawn
# from NREL ATB benchmarks. The BESS $/kWh value is a central 5-hour turnkey
# assumption; its fixed O&M follows the ATB's 2.5%-of-capex convention.
PV_CAPEX_USD_PER_KW_AC = 1_430.0
PV_FIXED_OM_USD_PER_KW_AC_YEAR = 24.0
BES_CAPEX_USD_PER_KWH = 300.0
BES_FIXED_OM_FRACTION_OF_CAPEX = 0.025
CSP_TES_CAPEX_USD_PER_KW_ELECTRIC = 7_912.0
CSP_TES_FIXED_OM_USD_PER_KW_ELECTRIC_YEAR = 74.6
CSP_TES_VARIABLE_OM_USD_PER_MWH_ELECTRIC = 3.8


def _repeat(values: list[float], hours: int = 24) -> list[float]:
    return list(islice(cycle(values), hours))


def _read_pnm_profile(filename: str) -> pd.Series:
    """Read a two-column PNM profile and normalize its timestamps to UTC."""
    path = DATA_DIRECTORY / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required example profile is missing: {path}")
    frame = pd.read_csv(path)
    if frame.shape[1] != 2 or "PNM" not in frame:
        raise ValueError(f"{path} must contain a timestamp column and a 'PNM' value column.")
    index = pd.to_datetime(frame.iloc[:, 0], utc=True, errors="raise")
    values = pd.to_numeric(frame["PNM"], errors="raise")
    if values.isna().any() or (values < 0).any():
        raise ValueError(f"{path} contains missing or negative availability/demand values.")
    return pd.Series(values.to_numpy(dtype=float), index=index, name="PNM")


def _pv_economics(pv_capacity_multiplier: float) -> tuple[float, float]:
    """Cost PV from its full-profile effective AC peak, not a study window."""
    effective_capacity_kW = _read_pnm_profile("PNM_pv_ac_1MW_av.csv").max() * pv_capacity_multiplier * 1_000
    return (
        effective_capacity_kW * PV_CAPEX_USD_PER_KW_AC,
        effective_capacity_kW * PV_FIXED_OM_USD_PER_KW_AC_YEAR,
    )


def _bes_economics(capacity_MWh: float) -> tuple[float, float]:
    capex = capacity_MWh * 1_000 * BES_CAPEX_USD_PER_KWH
    return capex, capex * BES_FIXED_OM_FRACTION_OF_CAPEX


def _csp_tes_economics(power_MW_electric: float) -> tuple[float, float]:
    power_kW = power_MW_electric * 1_000
    return (
        power_kW * CSP_TES_CAPEX_USD_PER_KW_ELECTRIC,
        power_kW * CSP_TES_FIXED_OM_USD_PER_KW_ELECTRIC_YEAR,
    )


def pnm_profiles(
    hours: int | None = None,
    start: str | pd.Timestamp | None = None,
    demand_multiplier: float = DEFAULT_DEMAND_MULTIPLIER,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return aligned PNM demand, PV AC, and CSP thermal hourly profiles.

    PV and CSP remain in the units provided by the data files. Demand is
    multiplied by ``demand_multiplier`` so the default examples represent a
    microgrid rather than the full PNM system; pass ``1.0`` for raw demand.
    """
    demand = _read_pnm_profile("PNM_demand.csv")
    pv = _read_pnm_profile("PNM_pv_ac_1MW_av.csv")
    csp = _read_pnm_profile("PNM_csp_th_av.csv")
    if not (demand.index.equals(pv.index) and demand.index.equals(csp.index)):
        raise ValueError("PNM demand, PV, and CSP profiles must share the same hourly timestamps.")
    if demand_multiplier < 0:
        raise ValueError("demand_multiplier must be non-negative.")
    demand = demand * demand_multiplier
    start_position = 0
    if start is not None:
        timestamp = pd.Timestamp(start)
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        positions = demand.index.get_indexer([timestamp])
        if positions[0] < 0:
            raise ValueError(f"start {start!r} is not an hourly PNM timestamp.")
        start_position = int(positions[0])
    if hours is None:
        hours = len(demand) - start_position
    if not isinstance(hours, int) or isinstance(hours, bool) or not 0 < hours <= len(demand) - start_position:
        raise ValueError(f"hours must be a positive integer no greater than {len(demand) - start_position}.")
    end_position = start_position + hours
    demand, pv, csp = demand.iloc[start_position:end_position], pv.iloc[start_position:end_position], csp.iloc[start_position:end_position]
    return demand.rename("load_MW"), pv.rename("pv_MW_electric"), csp.rename("csp_MW_thermal")


def load_profile(
    hours: int | None = None,
    start: str | pd.Timestamp | None = None,
    demand_multiplier: float = DEFAULT_DEMAND_MULTIPLIER,
) -> pd.Series:
    """PNM demand profile used by the public example systems."""
    return pnm_profiles(hours, start, demand_multiplier)[0]


def pv_bes_system(
    hours: int | None = None,
    start: str | pd.Timestamp | None = None,
    demand_multiplier: float = DEFAULT_DEMAND_MULTIPLIER,
    pv_capacity_multiplier: float = DEFAULT_PV_CAPACITY_MULTIPLIER,
    bes_capacity_MWh: float = DEFAULT_BES_CAPACITY_MWH,
    bes_power_MW: float = DEFAULT_BES_POWER_MW,
) -> System:
    """PV+BES example using the supplied PNM demand and PV availability."""
    load, pv_profile, _ = pnm_profiles(hours, start, demand_multiplier)
    if pv_capacity_multiplier < 0:
        raise ValueError("pv_capacity_multiplier must be non-negative.")
    site = Site("example_site")
    pv_capex, pv_opex = _pv_economics(pv_capacity_multiplier)
    bes_capex, bes_opex = _bes_economics(bes_capacity_MWh)
    pv = Generation("pv", site, pv_profile * pv_capacity_multiplier, "electric", capex=pv_capex, opex=pv_opex)
    bes = Storage(
        "bes", site, capacity_MWh=bes_capacity_MWh, power_rating_MW=bes_power_MW,
        stored_energy_type="electric", load_output_energy_type="electric",
        discharge_efficiency=0.90, maximum_stored_energy_rate_MW=bes_power_MW, start_full=False,
        capex=bes_capex, opex=bes_opex,
    )
    paths = [ChargingPath("pv", "bes", "electric", "electric", 0.90, bes_power_MW / 0.90)]
    return System(load, [bes, pv], paths)


def csp_tes_system(
    hours: int | None = None,
    start: str | pd.Timestamp | None = None,
    demand_multiplier: float = DEFAULT_DEMAND_MULTIPLIER,
    csp_capacity_multiplier: float = DEFAULT_CSP_CAPACITY_MULTIPLIER,
    tes_capacity_MWh_thermal: float = DEFAULT_TES_CAPACITY_MWH_THERMAL,
    tes_power_MW_electric: float = DEFAULT_TES_POWER_MW_ELECTRIC,
) -> System:
    """CSP+TES example using supplied PNM demand and thermal availability."""
    load, _, csp_profile = pnm_profiles(hours, start, demand_multiplier)
    if csp_capacity_multiplier < 0:
        raise ValueError("csp_capacity_multiplier must be non-negative.")
    site = Site("example_site")
    csp_capex, csp_opex = _csp_tes_economics(tes_power_MW_electric)
    csp = Generation(
        "csp", site, csp_profile * csp_capacity_multiplier, "thermal",
        can_supply_load=False, can_export=False, capex=csp_capex, opex=csp_opex,
    )
    tes = Storage(
        "tes", site, capacity_MWh=tes_capacity_MWh_thermal, power_rating_MW=tes_power_MW_electric,
        stored_energy_type="thermal", load_output_energy_type="electric",
        discharge_efficiency=0.50, maximum_stored_energy_rate_MW=DEFAULT_TES_MAX_CHARGE_MW_THERMAL,
        start_full=False,
        variable_opex_USD_per_MWh=CSP_TES_VARIABLE_OM_USD_PER_MWH_ELECTRIC,
    )
    paths = [ChargingPath("csp", "tes", "thermal", "thermal", 0.90, DEFAULT_TES_MAX_CHARGE_MW_THERMAL / 0.90)]
    return System(load, [tes, csp], paths)


def pv_csp_bes_tes_system(
    hours: int | None = None,
    start: str | pd.Timestamp | None = None,
    demand_multiplier: float = DEFAULT_DEMAND_MULTIPLIER,
    pv_capacity_multiplier: float = DEFAULT_PV_CAPACITY_MULTIPLIER,
    csp_capacity_multiplier: float = DEFAULT_CSP_CAPACITY_MULTIPLIER,
    bes_capacity_MWh: float = DEFAULT_BES_CAPACITY_MWH,
    bes_power_MW: float = DEFAULT_BES_POWER_MW,
    tes_capacity_MWh_thermal: float = DEFAULT_TES_CAPACITY_MWH_THERMAL,
    tes_power_MW_electric: float = DEFAULT_TES_POWER_MW_ELECTRIC,
) -> System:
    """Combined PV+CSP+BES+TES example using all supplied PNM profiles."""
    load, pv_profile, csp_profile = pnm_profiles(hours, start, demand_multiplier)
    if pv_capacity_multiplier < 0 or csp_capacity_multiplier < 0:
        raise ValueError("Capacity multipliers must be non-negative.")
    site = Site("example_site")
    pv_capex, pv_opex = _pv_economics(pv_capacity_multiplier)
    bes_capex, bes_opex = _bes_economics(bes_capacity_MWh)
    csp_capex, csp_opex = _csp_tes_economics(tes_power_MW_electric)
    csp = Generation(
        "csp", site, csp_profile * csp_capacity_multiplier, "thermal",
        can_supply_load=False, can_export=False, capex=csp_capex, opex=csp_opex,
    )
    pv = Generation("pv", site, pv_profile * pv_capacity_multiplier, "electric", capex=pv_capex, opex=pv_opex)
    tes = Storage(
        "tes", site, capacity_MWh=tes_capacity_MWh_thermal, power_rating_MW=tes_power_MW_electric,
        stored_energy_type="thermal", load_output_energy_type="electric",
        discharge_efficiency=0.50, maximum_stored_energy_rate_MW=DEFAULT_TES_MAX_CHARGE_MW_THERMAL,
        start_full=False,
        variable_opex_USD_per_MWh=CSP_TES_VARIABLE_OM_USD_PER_MWH_ELECTRIC,
    )
    bes = Storage(
        "bes", site, capacity_MWh=bes_capacity_MWh, power_rating_MW=bes_power_MW,
        stored_energy_type="electric", load_output_energy_type="electric",
        discharge_efficiency=0.90, maximum_stored_energy_rate_MW=bes_power_MW, start_full=False,
        capex=bes_capex, opex=bes_opex,
    )
    paths = [
        ChargingPath("csp", "tes", "thermal", "thermal", 0.90, DEFAULT_TES_MAX_CHARGE_MW_THERMAL / 0.90, priority=0),
        ChargingPath("pv", "bes", "electric", "electric", 0.90, bes_power_MW / 0.90, priority=0),
    ]
    # Storage order is load-serving priority: TES then BES.
    return System(load, [tes, csp, bes, pv], paths)


def csp_multiple_storage_system(
    hours: int | None = None,
    start: str | pd.Timestamp | None = None,
    demand_multiplier: float = DEFAULT_DEMAND_MULTIPLIER,
    csp_capacity_multiplier: float = DEFAULT_CSP_CAPACITY_MULTIPLIER,
) -> System:
    """PNM CSP charges TES and BES through separate typed conversion paths."""
    load, _, csp_profile = pnm_profiles(hours, start, demand_multiplier)
    if csp_capacity_multiplier < 0:
        raise ValueError("csp_capacity_multiplier must be non-negative.")
    site = Site("example_site")
    csp_capex, csp_opex = _csp_tes_economics(DEFAULT_TES_POWER_MW_ELECTRIC)
    bes_capex, bes_opex = _bes_economics(DEFAULT_BES_CAPACITY_MWH)
    csp = Generation(
        "csp", site, csp_profile * csp_capacity_multiplier, "thermal", False, False,
        capex=csp_capex, opex=csp_opex,
    )
    tes = Storage(
        "tes", site, DEFAULT_TES_CAPACITY_MWH_THERMAL, DEFAULT_TES_POWER_MW_ELECTRIC,
        "thermal", "electric", 0.50, maximum_stored_energy_rate_MW=DEFAULT_TES_MAX_CHARGE_MW_THERMAL,
        variable_opex_USD_per_MWh=CSP_TES_VARIABLE_OM_USD_PER_MWH_ELECTRIC,
    )
    bes = Storage(
        "bes", site, DEFAULT_BES_CAPACITY_MWH, DEFAULT_BES_POWER_MW,
        "electric", "electric", 0.90, maximum_stored_energy_rate_MW=DEFAULT_BES_POWER_MW,
        capex=bes_capex, opex=bes_opex,
    )
    paths = [
        ChargingPath("csp", "tes", "thermal", "thermal", 0.90, MULTI_STORAGE_TES_MAX_INPUT_MW_THERMAL, priority=0),
        ChargingPath("csp", "bes", "thermal", "electric", 0.40, DEFAULT_BES_POWER_MW / 0.40, priority=1),
    ]
    return System(load, [tes, bes, csp], paths)


# These fixtures preserve short, deterministic legacy-dispatch signatures for
# regression tests. Public notebook examples use ``pnm_profiles`` above.
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


def show(system: System) -> None:
    """Print a compact audit of source, stored, and load-energy flows."""
    df = system.timeseries
    flow_columns = [column for column in df if "_to_" in column or column.startswith("grid_to_")]
    print(df[flow_columns].sum().round(4).to_string())
    print("\nFirst six hours")
    print(df.head(6).round(4).to_string())
