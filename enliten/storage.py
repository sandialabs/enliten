# -*- coding: utf-8 -*-
class Storage_System:
    def __init__(self, name, site, capacity_MWh, power_type, energy_type, power_rating_MW, power_minimum_MW, systems_charging, percent_discharge_depth, charge_efficiency, baseload, percent_loss_daily, charge_rate_MW, off_grid_operation, start_full, conversion_values, capex=None, opex=None):
           
        self.name = name
        self.site = site
        self.capacity_MWh = capacity_MWh
        self.power_type = power_type
        self.energy_type = energy_type
        self.power_rating_MW = power_rating_MW
        self.power_minimum_MW = power_minimum_MW
        self.systems_charging = systems_charging
        self.percent_discharge_depth=abs(percent_discharge_depth)
        self.percent_loss_daily=abs(percent_loss_daily)
        self.charge_rate_MW = charge_rate_MW
        # self.charge_rate_resistive_MW=charge_rate_resistive_MW
        self.charge_efficiency = charge_efficiency
        # self.discharge_efficiency = discharge_efficiency
        self.baseload = baseload
        self.off_grid_operation = off_grid_operation
        self.start_full = start_full
        self.conversion_values = conversion_values
        self.capex = capex
        self.opex = opex
