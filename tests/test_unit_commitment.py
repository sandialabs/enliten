import pandas as pd
import pytest

from enliten import Generation, Site, Storage, System
from examples.common import csp_tes_system, pv_bes_system, pv_csp_bes_tes_system


def assert_values(frame, column, expected):
    assert frame[column].iloc[: len(expected)].tolist() == pytest.approx(expected)


def test_pv_bes_matches_legacy_dispatch_signature():
    """Signature recorded from the supplied legacy package's effective logic."""
    df = pv_bes_system(hours=16).timeseries
    assert_values(df, "pv_to_load_MWh", [0, 6, 7, 0, 0])
    assert_values(df, "pv_to_bes_MWh", [0, 2, 3, 0, 0])
    assert_values(df, "bes_MWh", [0, 1.8, 4.5, 1 / 18, 0])
    assert_values(df, "bes_to_load_MWh", [0, 0, 0, 4, 0.05])


def test_csp_tes_matches_legacy_dispatch_signature():
    df = csp_tes_system(hours=16).timeseries
    assert_values(df, "csp_to_tes_MWh", [0, 8, 0, 4, 6])
    assert_values(df, "tes_to_load_MWh", [0, 3.6, 0, 1.8, 2.7])
    assert_values(df, "grid_to_load_MWh", [0, 2.4, 7, 2.2, 2.3])


def test_pv_csp_bes_tes_matches_legacy_dispatch_signature():
    """The combined-case rows match the supplied legacy System.operation."""
    df = pv_csp_bes_tes_system(hours=16).timeseries
    assert_values(df, "csp_to_tes_MWh", [0, 8, 0, 4, 6])
    assert_values(df, "pv_to_load_MWh", [0, 6, 7, 0, 0])
    assert_values(df, "tes_to_load_MWh", [0, 0, 0, 4, 4.1])
    assert_values(df, "bes_to_load_MWh", [0, 0, 0, 0, 0.9])
    assert_values(df, "grid_to_load_MWh", [0, 0, 0, 0, 0])


def test_reserve_is_an_explicit_storage_characteristic():
    site = Site("site")
    storage = Storage(
        "storage",
        site,
        capacity_MWh=10,
        power_rating_MW=10,
        systems_charging=[],
        discharge_efficiency=1,
        minimum_state_of_charge_MWh=2,
        start_full=True,
    )
    result = System(pd.Series([10.0, 10.0], name="load_MW"), [storage]).timeseries
    assert result.loc[1, "storage_to_load_MWh"] == pytest.approx(8)
    assert result.loc[1, "storage_MWh"] == pytest.approx(2)
