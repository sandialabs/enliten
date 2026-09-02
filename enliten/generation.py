# -*- coding: utf-8 -*-
class Power_System:
    def __init__(self, name, site, power_type, energy_type, capacity_MW,  off_grid_operation, to_load, power_timeseries, power_priority_load_MW = None, capex=None, opex=None, land_area=None):
        
        self.name = name
        self.site = site
        self.power_type = power_type 
        self.energy_type = energy_type
        self.capacity_MW = capacity_MW   
        self.off_grid_operation = off_grid_operation
        self.to_load = to_load
        self.power_timeseries = power_timeseries
        self.power_priority_load_MW = power_priority_load_MW   
        self.capex = capex
        self.opex = opex
        self.land_area = land_area
