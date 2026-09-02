# ENLITEN

ENLITEN is a technology-agnostic, hourly unit-commitment package for energy
systems with any combination of generation and storage assets. Resource models
(PV, CSP, wind, generators, and so on) stay upstream and provide an hourly
power time series. The dispatcher only needs each asset's operating
characteristics and charging relationships.

## Install and test

```powershell
python -m pip install -e .
python -m pytest
```

The focused regression suite covers the requested PV+BES, CSP+TES, and
PV+CSP+BES+TES configurations. The test signatures were recorded by running
the supplied legacy dispatcher on deterministic fixtures, then compared with
the generic dispatcher. They intentionally do not depend on resource-model
packages or Sandia-specific files.

## Run examples

```powershell
python examples/pv_bes.py
python examples/csp_tes.py
python examples/pv_csp_bes_tes.py
```

Each example prints an energy-flow summary and the first six hours of its
auditable dispatch DataFrame. Replace the short deterministic profiles in
`examples/common.py` with production resource and load time series when doing
an application study.

## Model

```python
from enliten import Generation, Site, Storage, System

site = Site("plant")
pv = Generation("pv", site, pv_mw, can_supply_load=True)
battery = Storage(
    "battery", site,
    capacity_MWh=30,
    power_rating_MW=10,
    systems_charging=["pv"],
    charge_efficiency={"pv": 0.92},
    discharge_efficiency=0.92,
    charge_rate_MW=10,
)
result = System(load_mw, [battery, pv]).timeseries
```

Generation attributes describe an available power time series, whether it can
directly serve electric load, and its connection site. Storage attributes
describe capacity, charge/discharge limits, efficiencies, loss, starting
state, reserve, and the *names* of allowable charging sources. A thermal store
is the same `Storage` class as a battery; provide its thermal-to-electric
conversion efficiency (constant or hourly sequence) as
`discharge_efficiency`.

Asset order is deliberate policy. Non-load-serving generators charge their
compatible storage first. Load-serving generators serve load and then charge
storage. Storage assets serve residual load in the order in which they are
passed to `System`. This permits the old CSP->TES, PV->load/charge,
TES->load, BES->load priority without technology-specific conditionals.

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

## Scope of the comparison

The original archive does not include the ASGARD weather or load inputs used
by its former notebooks. Consequently this repository verifies identical
dispatch logic on deterministic fixtures, not the historical ASGARD annual
outputs. To certify a production comparison, run the same input time series in
separate legacy and generic environments and compare named load, charge,
state-of-charge, export, and curtailment columns.
