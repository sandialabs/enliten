# ENLITEN

ENLITEN is a technology-agnostic, hourly unit-commitment package for energy
systems with any combination of generation and storage assets. Resource models
(PV, CSP, wind, generators, and so on) stay upstream and provide an hourly
power time series. The dispatcher only needs each asset's operating
characteristics and charging relationships.

## Install and test

```powershell
python -m pip install -e ".[notebooks]"
python -m pytest
jupyter notebook examples
```

The focused regression suite covers the requested PV+BES, CSP+TES, and
PV+CSP+BES+TES configurations. The test signatures were recorded by running
the supplied legacy dispatcher on deterministic fixtures, then compared with
the generic dispatcher. They intentionally do not depend on resource-model
packages or Sandia-specific files.

## Run examples

Open the notebooks in `examples/`:

- `pv_bes.ipynb` — PV + BES, TEA inputs, dispatch plots, and resilience.
- `csp_tes.ipynb` — CSP + TES with thermal charging and electric load output.
- `pv_csp_bes_tes.ipynb` — the combined four-technology configuration.
- `csp_multiple_storage.ipynb` — one CSP asset charging thermal and electric
  stores at distinct conversion efficiencies and rates.

They use short deterministic fixtures from `examples/common.py`; replace those
with production resource and load time series for an application study.

## Model

```python
from enliten import ChargingPath, Generation, Site, Storage, System

site = Site("plant")
pv = Generation("pv", site, pv_mw, output_energy_type="electric")
battery = Storage(
    "battery", site,
    capacity_MWh=30,
    power_rating_MW=10,
    stored_energy_type="electric",
    load_output_energy_type="electric",
    discharge_efficiency=0.92,
)
pv_to_battery = ChargingPath(
    "pv", "battery",
    source_energy_type="electric",
    stored_energy_type="electric",
    input_to_stored_efficiency=0.92,
    maximum_input_rate_MW=10,
)
result = System(load_mw, [battery, pv], [pv_to_battery]).timeseries
```

Generation declares the energy type of its available power time series.
Storage declares its stored-energy and load-output types; a thermal store is
therefore the same `Storage` class as a battery, with a thermal state of charge
and a thermal-to-electric `discharge_efficiency` (constant or hourly).
`ChargingPath` declares each permitted generation-to-storage connection, its
source and stored-energy types, input-to-stored efficiency, and maximum input
rate in the **source** energy unit.

For example, CSP->TES uses a thermal input rate and creates thermal stored
energy; PV->BES uses electric units throughout; CSP->BES can use a thermal
input, electric stored energy, and an explicit thermal-to-electric conversion
efficiency. The DataFrame records both sides, such as
`csp_to_bes_MWh_thermal` and `csp_to_bes_stored_MWh_electric`, so energy types
are never silently mixed.

Asset order is deliberate policy. Non-load-serving generators charge their
compatible storage first. Load-serving generators serve load and then charge
storage. `ChargingPath.priority` selects among a generator's charging routes;
storage assets serve residual load in the order in which they are passed to
`System`. This permits the old CSP->TES, PV->load/charge, TES->load,
BES->load priority without technology-specific conditionals.

## Storage reserve and the legacy BES line

Storage capacity is fully dispatchable by default. Set
`minimum_state_of_charge_MWh` when a reserve is required. The supplied legacy
`system.py` computes a BES depth-of-discharge limit at line 931 but immediately
overwrites it at line 936 with `bes_avail = max(0, bes_MWh)`. Its effective
behavior is therefore full dispatchability; the generic PV+BES compatibility
case states that behavior explicitly with the default zero reserve. No code
line needs to be commented out.

If a 30 MWh battery is meant to retain 20% state of charge, model that intent
directly with `minimum_state_of_charge_MWh=6`; this will, correctly, differ
from the legacy bug-compatible result.

## Metrics, resilience, and plotting

`System.timeseries` is the auditable hourly ledger. `System.system_metrics()`
(or its `tea_metrics()` alias) calculates the normal-operation totals and
annualized TEA inputs directly from that ledger: system/load/grid/export MWh,
capex, fixed O&M, variable O&M, electricity-sale revenue, grid-purchase cost,
and `system_augment`. Annual values are scaled from non-calendar fixture data
or grouped by calendar year when the input has a `DatetimeIndex`.

Use `resilience_cases` to run grid-unavailable dispatch with the same asset and
conversion-path model:

```python
cases = system.resilience_cases(
    critical_load_MW=2.0,
    target_hours=72,
    n_starts=100,
    seed=7,
)
print(system.resilience_summary)
```

Only assets with `off_grid_operation=True` participate. Each random start is
evaluated using the normal-operation state of charge (`actual`) and a full-store
counterfactual (`full`). The returned table contains durations, target-energy
service, and unmet target energy; `resilience_summary` contains target-success
rates and 10th/50th/90th-percentile metrics. Pass `start_hours=[...]` when the
starts must be exactly prescribed instead of random.

The original plotting workflow is available without importing plotting
libraries until it is used: `timeseries_plot_source`,
`timeseries_plot_group`, and `plot_storage_capacity` each return `(figure,
axis)`. Matplotlib is installed with ENLITEN.

## Scope of the comparison

The original archive does not include the ASGARD weather or load inputs used
by its former notebooks. Consequently this repository verifies identical
dispatch logic on deterministic fixtures, not the historical ASGARD annual
outputs. To certify a production comparison, run the same input time series in
separate legacy and generic environments and compare named load, charge,
state-of-charge, export, and curtailment columns.
