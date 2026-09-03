"""Technology-economic analysis calculator restored from the original ENLITEN.

The public ``LCOECalculator`` API and core cash-flow calculation are retained.
This version additionally accepts the annual lists emitted by the generic
``System.operation_metrics()`` method and provides :meth:`from_system` as the
preferred integration point.
"""

from __future__ import annotations

from numbers import Real
from typing import TYPE_CHECKING, Sequence

import numpy as np
import numpy_financial as npf

if TYPE_CHECKING:
    from .system import System


def _annual_value(value: Real | Sequence[float] | np.ndarray, name: str) -> float:
    """Return a representative annual value from a scalar or annual series."""
    values = np.asarray(value, dtype=float).reshape(-1)
    if values.size == 0:
        raise ValueError(f"{name} must not be empty.")
    if not np.isfinite(values).all():
        raise ValueError(f"{name} must contain only finite values.")
    return float(values.mean())


class LCOECalculator:
    """Original ENLITEN LCOE/TEA calculator, compatible with generic metrics."""

    def __init__(
        self,
        system_capex_USD: float,
        system_annual_OM_USD: float,
        system_annual_VOM_USD: float,
        system_to_load_annual_MWh_e: Real | Sequence[float],
        system_augment: Sequence[float] | np.ndarray,
        ITC: float = 0.5,
        DF: float = 0.5,
        COE: float = 0.13,
        I: float = 0.08,
        grant_percentage: float = 0,
        tax: float = 0.257,
        inflation: float = 0.028,
        property_tax: float = 0.0084,
        insurance: float = 0.004,
        depreciation_period: int = 5,
        esc: float = 0.028,
        analysis_period: int = 30,
        VOM: float = 0.003,
        e_sale: float = 0.07,
        annual_electricity_sales_USD: Real | Sequence[float] | None = None,
        annual_electricity_purchases_USD: Real | Sequence[float] | None = None,
    ) -> None:
        self.system_capex_USD = float(system_capex_USD)
        self.system_annual_OM_USD = float(system_annual_OM_USD)
        self.system_annual_VOM_USD = float(system_annual_VOM_USD)
        self.system_to_load_annual_MWh_e = system_to_load_annual_MWh_e
        self.system_augment = np.asarray(system_augment, dtype=float).reshape(-1)
        self.ITC, self.DF, self.COE, self.I = ITC, DF, COE, I
        self.grant_percentage, self.tax, self.inflation = grant_percentage, tax, inflation
        self.property_tax, self.insurance = property_tax, insurance
        self.depreciation_period, self.esc, self.analysis_period = depreciation_period, esc, analysis_period
        self.VOM, self.e_sale = VOM, e_sale
        self.annual_electricity_sales_USD = annual_electricity_sales_USD
        self.annual_electricity_purchases_USD = annual_electricity_purchases_USD
        if analysis_period <= 0 or depreciation_period <= 0:
            raise ValueError("analysis_period and depreciation_period must be positive.")

    @classmethod
    def from_system(cls, system: "System", **tea_options: object) -> "LCOECalculator":
        """Build the original calculator from generic dispatch-derived metrics.

        Generic systems report electricity values under explicit unit-bearing
        names. Calendar-indexed, multi-year runs are reduced to a mean annual
        value because this calculator models a representative project year.
        """
        if system.load_energy_type != "electric":
            raise ValueError("LCOECalculator.from_system requires an electric load-energy system.")
        metrics = system.operation_metrics()
        return cls(
            system_capex_USD=metrics["system_capex_USD"],
            system_annual_OM_USD=metrics["system_annual_OM_USD"],
            system_annual_VOM_USD=metrics["system_annual_VOM_USD"],
            system_to_load_annual_MWh_e=metrics["system_to_load_annual_MWh_electric"],
            system_augment=metrics["system_augment"],
            annual_electricity_sales_USD=metrics["annual_electricity_sales_USD"],
            annual_electricity_purchases_USD=metrics["annual_electricity_purchases_USD"],
            **tea_options,
        )

    def augment_array_np(self, arr: Sequence[float] | np.ndarray, length: int) -> np.ndarray:
        """Restore the original augmentation helper with reliable list support."""
        values = np.asarray(arr, dtype=float).reshape(-1)
        if values.size == 0:
            values = np.zeros(1)
        values = np.insert(values, 0, 0.0) if values[0] != 0 else values
        if values.size >= length:
            return values[:length]
        repeat_values = values[1:] if values.size > 1 else values
        return np.concatenate((values, np.resize(repeat_values, length - values.size)))

    def calculate_depreciation(
        self,
        analysis_period: int | None = None,
        system_capex_USD: float | None = None,
        inflation: float | None = None,
        depreciation_period: int | None = None,
        ITC: float | None = None,
    ) -> tuple[list[float], list[float]]:
        """Calculate the original declining-balance depreciation schedule."""
        analysis_period = self.analysis_period if analysis_period is None else analysis_period
        capex = self.system_capex_USD if system_capex_USD is None else system_capex_USD
        inflation = self.inflation if inflation is None else inflation
        period = self.depreciation_period if depreciation_period is None else depreciation_period
        ITC = self.ITC if ITC is None else ITC
        base = capex * (1 - ITC / 2)
        remaining = base
        values, fractions = [0.0], [0.0]
        for year in range(1, analysis_period + 1):
            if year <= period and base:
                depreciation = min(remaining * 2 / period, remaining) * (1 - inflation) ** year
                values.append(depreciation)
                fractions.append(depreciation / base)
                remaining -= min(remaining * 2 / period, remaining)
            else:
                values.append(0.0)
                fractions.append(0.0)
        return values, fractions

    def calculate_lcoe_metrics(self, **overrides: object) -> dict[str, float | int | None]:
        """Calculate the original real before- and after-tax LCOE metrics."""
        get = lambda name: overrides.get(name, getattr(self, name))
        capex = float(get("system_capex_USD"))
        annual_om = float(get("system_annual_OM_USD"))
        annual_vom = float(get("system_annual_VOM_USD"))
        annual_energy_mwh = _annual_value(get("system_to_load_annual_MWh_e"), "system_to_load_annual_MWh_e")
        if annual_energy_mwh <= 0:
            raise ValueError("system_to_load_annual_MWh_e must be positive to calculate LCOE.")
        period = int(get("analysis_period"))
        tax, inflation, esc = float(get("tax")), float(get("inflation")), float(get("esc"))
        ITC, DF, COE, interest = float(get("ITC")), float(get("DF")), float(get("COE")), float(get("I"))
        grant, insurance, property_tax = float(get("grant_percentage")), float(get("insurance")), float(get("property_tax"))
        WACC_n = DF * interest * (1 - tax) + (1 - DF) * COE
        WACC_r = (1 + WACC_n) / (1 + inflation) - 1
        CRF = WACC_r / (1 - (1 + WACC_r) ** (-period))

        annual_OM = np.r_[0.0, [annual_om * (1 + esc) ** year for year in range(1, period + 1)]]
        annual_VOM = np.r_[0.0, [annual_vom * (1 + esc) ** year for year in range(1, period + 1)]]
        sales_input = overrides.get("annual_electricity_sales_USD", self.annual_electricity_sales_USD)
        purchase_input = overrides.get("annual_electricity_purchases_USD", self.annual_electricity_purchases_USD)
        sales = annual_energy_mwh * 1000 * float(get("e_sale")) if sales_input is None else _annual_value(sales_input, "annual_electricity_sales_USD")
        purchases = 0.0 if purchase_input is None else _annual_value(purchase_input, "annual_electricity_purchases_USD")
        annual_sales = np.r_[0.0, np.repeat(sales, period)]
        annual_purchases = np.r_[0.0, [purchases * (1 + esc) ** year for year in range(1, period + 1)]]
        annual_energy_kwh = np.r_[0.0, np.repeat(annual_energy_mwh * 1000, period)]
        augment = self.augment_array_np(overrides.get("system_augment", self.system_augment), period + 1)
        depreciation, fractions = self.calculate_depreciation(
            period, capex * (1 - grant), inflation, int(get("depreciation_period")), ITC
        )
        pvd = sum(fractions[year] / (1 + WACC_r) ** year for year in range(min(len(fractions), int(get("depreciation_period")) + 1)))
        fcr_at = CRF * (1 - tax * pvd * (1 - ITC / 2) - ITC) + (insurance + property_tax) * (1 - tax)
        fcr_bt = (CRF * (1 - tax * pvd * (1 - ITC / 2) - ITC) + insurance + property_tax) / (1 - tax)
        npv = lambda values: float(npf.npv(WACC_r, values))
        npv_energy = npv(annual_energy_kwh)
        npv_om, npv_vom, npv_augment = npv(annual_OM), npv(annual_VOM), npv(augment)
        annual_arr_at = capex * (1 - grant) * fcr_at + (npv_om + npv_vom + npv(annual_purchases) + npv_augment) * CRF * (1 - tax)
        annual_arr_bt = capex * (1 - grant) * fcr_bt + (npv_om + npv_vom + npv(annual_purchases) + npv_augment) * CRF
        cash_flow = [-(capex * (1 - ITC) * (1 - grant))]
        unused_depreciation = 0.0
        for year in range(1, period + 1):
            ebit = annual_sales[year] - annual_OM[year] - annual_VOM[year] - annual_purchases[year] - augment[year]
            taxable = max(0.0, ebit - depreciation[year] - unused_depreciation)
            unused_depreciation = max(0.0, depreciation[year] + unused_depreciation - ebit)
            cash_flow.append(ebit - taxable * tax - (insurance + property_tax) * capex * (1 - grant))
        cumulative = np.cumsum(cash_flow)
        payback = next((year for year, value in enumerate(cumulative) if value >= -cash_flow[0]), None)
        return {
            "PVD": float(pvd), "FCR_AT": float(fcr_at), "FCR_BT": float(fcr_bt), "CRF": float(CRF),
            "NPV_cash_flow": npv(cash_flow), "IRR": float(npf.irr(cash_flow)), "payback_period": payback,
            "LCOE_real_USD_kWh_BT": float(npv(np.r_[0.0, np.repeat(annual_arr_bt, period)]) / npv_energy),
            "LCOE_real_USD_kWh_AT": float(npv(np.r_[0.0, np.repeat(annual_arr_at, period)]) / npv_energy),
        }
