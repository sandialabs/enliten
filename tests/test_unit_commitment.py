import pandas as pd
import pytest

from enliten import ChargingPath, Generation, LCOECalculator, Site, Storage, System
from tests.fixtures import (
    fixture_csp_multiple_storage_system,
    fixture_csp_tes_system,
    fixture_pv_bes_system,
    fixture_pv_csp_bes_tes_system,
)


def assert_values(frame, column, expected):
    assert frame[column].iloc[: len(expected)].tolist() == pytest.approx(expected)


def test_pv_bes_matches_legacy_dispatch_signature_with_typed_flows():
    df = fixture_pv_bes_system(hours=16).timeseries
    assert_values(df, "pv_to_load_MWh_electric", [0, 6, 7, 0, 0])
    assert_values(df, "pv_to_bes_MWh_electric", [0, 2, 3, 0, 0])
    assert_values(df, "pv_to_bes_stored_MWh_electric", [0, 1.8, 2.7, 0, 0])
    assert_values(df, "bes_MWh_electric", [0, 1.8, 4.5, 1 / 18, 0])
    assert_values(df, "bes_to_load_MWh_electric", [0, 0, 0, 4, 0.05])


def test_csp_tes_tracks_thermal_input_and_storage_separately_from_electric_load():
    df = fixture_csp_tes_system(hours=16).timeseries
    assert_values(df, "csp_to_tes_MWh_thermal", [0, 8, 0, 4, 6])
    assert_values(df, "csp_to_tes_stored_MWh_thermal", [0, 7.2, 0, 3.6, 5.4])
    assert_values(df, "tes_to_load_MWh_electric", [0, 3.6, 0, 1.8, 2.7])
    assert_values(df, "grid_to_load_MWh_electric", [0, 2.4, 7, 2.2, 2.3])


def test_pv_csp_bes_tes_matches_legacy_dispatch_signature_with_typed_ledgers():
    df = fixture_pv_csp_bes_tes_system(hours=16).timeseries
    assert_values(df, "csp_to_tes_MWh_thermal", [0, 8, 0, 4, 6])
    assert_values(df, "pv_to_load_MWh_electric", [0, 6, 7, 0, 0])
    assert_values(df, "tes_to_load_MWh_electric", [0, 0, 0, 4, 4.1])
    assert_values(df, "bes_to_load_MWh_electric", [0, 0, 0, 0, 0.9])
    assert_values(df, "grid_to_load_MWh_electric", [0, 0, 0, 0, 0])


def test_one_generation_asset_charges_multiple_storage_types_via_typed_paths():
    df = fixture_csp_multiple_storage_system().timeseries
    assert df.loc[1, "csp_to_tes_MWh_thermal"] == pytest.approx(6.0)
    assert df.loc[1, "csp_to_tes_stored_MWh_thermal"] == pytest.approx(5.4)
    assert df.loc[1, "csp_to_bes_MWh_thermal"] == pytest.approx(4.0)
    assert df.loc[1, "csp_to_bes_stored_MWh_electric"] == pytest.approx(1.6)
    assert df.loc[1, "tes_MWh_thermal"] == pytest.approx(5.4)
    assert df.loc[1, "bes_MWh_electric"] == pytest.approx(1.6)


def test_energy_types_are_validated_at_each_connection():
    site = Site("site")
    csp = Generation("csp", site, [0.0, 1.0], output_energy_type="thermal", can_supply_load=False)
    battery = Storage("battery", site, 1.0, 1.0, stored_energy_type="electric")
    wrong_path = ChargingPath("csp", "battery", "electric", "electric", 0.9)
    with pytest.raises(ValueError, match="source_energy_type"):
        System(pd.Series([0.0, 0.0]), [csp, battery], [wrong_path])


def test_reserve_is_an_explicit_storage_characteristic():
    site = Site("site")
    storage = Storage(
        "storage", site, capacity_MWh=10, power_rating_MW=10,
        minimum_state_of_charge_MWh=2, start_full=True,
    )
    result = System(pd.Series([10.0, 10.0], name="load_MW"), [storage]).timeseries
    assert result.loc[1, "storage_to_load_MWh_electric"] == pytest.approx(8)
    assert result.loc[1, "storage_MWh_electric"] == pytest.approx(2)


def test_normal_metrics_provide_tea_ready_annual_inputs():
    system = fixture_pv_bes_system(hours=16)
    metrics = system.operation_metrics()

    assert metrics["operating_hours"] == 15
    assert metrics["unmet_load_MWh_electric"] == pytest.approx(0)
    assert metrics["system_to_load_MWh_electric"] > 0
    assert metrics["grid_to_load_MWh_electric"] > 0
    assert len(metrics["system_to_load_annual_MWh_electric"]) == 1
    assert len(metrics["annual_electricity_sales_USD"]) == 1
    assert metrics["system_augment"] == metrics["system_augment_USD"]


def test_partial_calendar_year_metrics_are_annualized():
    index = pd.date_range("2023-07-01", periods=25, freq="h", tz="UTC")
    generator = Generation("generator", Site("site"), [0.0] + [1.0] * 24, "electric")
    system = System(pd.Series([1.0] * 25, index=index, name="load_MW"), [generator])

    assert system.metrics["operating_hours"] == 24
    assert system.metrics["system_to_load_annual_MWh_electric"] == pytest.approx([8760.0])


def test_resilience_supports_seeded_user_defined_random_starts_and_metrics():
    system = fixture_pv_bes_system(hours=16)
    cases = system.resilience_cases(
        critical_load_MW=2.0, target_hours=4, n_starts=5, seed=42
    )

    assert len(cases) == 5
    assert cases["start_hour"].tolist() == [3, 0, 8, 7, 7]
    assert cases["actual_duration_hours"].between(0, 4).all()
    assert cases["full_duration_hours"].between(0, 4).all()
    assert system.resilience_summary["n_starts"] == 5
    assert 0 <= system.resilience_summary["pct_meets_actual"] <= 100


def test_resilience_can_use_explicit_starts_and_excludes_non_islandable_assets():
    site = Site("site")
    generator = Generation(
        "grid_tied_pv", site, [0.0, 10.0, 10.0], "electric", off_grid_operation=False
    )
    system = System(pd.Series([1.0, 1.0, 1.0], name="load_MW"), [generator])

    cases = system.resilience_cases(1.0, target_hours=2, start_hours=[0, 1])
    assert cases["actual_duration_hours"].tolist() == [0, 0]
    assert cases["full_duration_hours"].tolist() == [0, 0]


def test_plot_functions_return_figures_without_displaying_them():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    system = fixture_pv_bes_system(hours=32)
    figures = [
        system.timeseries_plot_source(start_date=0, days=1),
        system.timeseries_plot_group(start_date=0, days=1),
        system.plot_storage_capacity(start_date=0, days=1),
    ]
    for figure, axis in figures:
        assert figure.axes == [axis]
        plt.close(figure)


def test_original_tea_calculator_adapts_generic_system_metrics():
    site = Site("site")
    generator = Generation(
        "generator", site, [0.0, 5.0, 5.0], "electric",
        capex=100_000.0, opex=2_000.0, variable_opex_USD_per_MWh=1.0,
    )
    system = System(
        pd.Series([5.0, 5.0, 5.0], name="load_MW"), [generator],
        grid_energy_cost_USD_per_kWh=0.10,
    )

    calculator = LCOECalculator.from_system(system, analysis_period=20)
    tea = calculator.calculate_lcoe_metrics()

    assert calculator.system_to_load_annual_MWh_e == system.metrics["system_to_load_annual_MWh_electric"]
    assert tea["LCOE_real_USD_kWh_AT"] > 0
    assert tea["LCOE_real_USD_kWh_BT"] > 0
