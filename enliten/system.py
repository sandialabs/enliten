# self.tes_baseload == False:
# self.metrics = self.system_metrics()
# -*- coding: utf-8 -*-
"""
system.py: hybrid system power flows
"""
from storage import *
from generation import *
from itertools import cycle, islice, chain
from random import randrange
import datetime as DT
from matplotlib import pyplot as plt
import matplotlib.ticker as ticker
import numpy_financial as npf
import multiprocess as mp
from random import randint
import os

class System: #need to set dict objects to exclude timeseries for metrics
    """
    This class accounts for energy flows within a hybrid renewable energy system including PV, BES, CSP, and TES systems.
    Uses classes for each of the above system types.
    Accepts variable loads.
    Customizable dispatch strategies.
    Charging and dispatch orders are set in the parameters.

    Parameters:

    - load_MW (pandas dataframe): hourly timeseries pandas dataframe with datetime as index and load quantified in MW.
    - systems_load_order (list): list of PV, BES, CSP and TES systems to be integrated. Order within each category determines dispatch and charging priority.

    Returns: Class object with the following attributes

    - self.timeseries (pandas dataframe): hourly timeseries of power flows in normal operation
    - self.metrics (dict): system performance metrics for normal operation

    Functions: Class object functions can be called to:

    - self.timeseries_plot_source(start_date='random',days=7,type='area'): produces a bar or area plot of the energy flows to load
    - self.timeseries_plot_group(start_date='random',days=7): same as above but sources are grouped by class
    """
    
    def __init__(self, load_MW, systems_load_order, grant_pct = 0, e_sale = 0.07, e_sale_factors = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], load_factor = 1, target_load_MW=None, tes_baseload = False, pv_to_load = True, tes_gasbackup = False):
        self.load_MW = load_MW
        self.systems = systems_load_order
        self.system_names = [sys.name for sys in self.systems]
        self.sites = list(set([sys.site for sys in self.systems]))

        self.target_load_MW = target_load_MW
        self.tes_baseload = tes_baseload
        self.pv_to_load = pv_to_load
        self.tes_gasbackup = tes_gasbackup
        self.e_sale = e_sale
        self.e_sale_factors = e_sale_factors
        self.load_factor = load_factor

        #separating systems by type
        self.power_systems = [sys for sys in self.systems if isinstance(sys,Power_System)]
        self.storage_systems = [sys for sys in self.systems if isinstance(sys,Storage_System)]

        #defining off-grid systems
        self.off_grid_systems = [sys for sys in self.systems if sys.off_grid_operation==True]

        self.power_systems_off_grid = [sys for sys in self.off_grid_systems if isinstance(sys,Power_System)]
        self.storage_systems_off_grid = [sys for sys in self.off_grid_systems if isinstance(sys,Storage_System)]
        
        self.timeseries = self.operation()

    def operational_systems(self, operation):
        if operation=='normal':
            power_systems = self.power_systems
            storage_systems = self.storage_systems

        elif operation=='off_grid':
            power_systems = self.power_systems_off_grid
            storage_systems = self.storage_systems_off_grid
        
        return power_systems, storage_systems

    def initialize_df(self, operation='normal', critical_load_MW = None, target_hours = None, df_res = None, res_initial = None):

        #determining which systems are being used (dynamic for off-grid scenario)
        power_systems, storage_systems = self.operational_systems(operation)

        #load handling
        if operation == 'normal':
            df = self.load_MW.copy().reset_index(inplace=False)
            df.load_MW = df.load_MW.abs()  # load is positive
            
            if self.target_load_MW is not None:
                # Ensure the indices align properly
                self.target_load_MW.index = df.index
                df['target_load_MW'] = self.target_load_MW
                df.target_load_MW = df.target_load_MW.abs()
            else:
                df['target_load_MW'] = None
        elif operation == 'off_grid':
            
            df = df_res.load_MW.copy().reset_index(inplace=False)
            df['target_load_MW'] = None    
            df.load_MW = critical_load_MW
            
        numrec = len(df)

        df['grid_to_load_MWh_e'] = 0
        df['unmet_target_load_MWh_e'] = 0
        df['export_energy_MWh_e'] = 0
        df['electricity_sale_in_hour'] = 0

        for power in power_systems:
            if operation == 'normal':
                #ts = power.power_timeseries
                ts = power.power_timeseries
            elif operation == 'off_grid':
                pass

            if len(ts) >= numrec:
                ts = ts[:numrec]
            else:
                ts = list(islice(cycle(ts), numrec))
                    
            df[power.name+'_power_MW'] = ts
            df[power.name+'_to_load_MWh'] = 0
            df[power.name+'_to_grid_MWh'] = 0
            df[power.name+'_curtailed_MWh'] = 0
            # df[power.name+'_heat_unused_MWh'] = 0
            # since time series provided, just use curtailed

            for storage in storage_systems:
                if power.name in storage.systems_charging: #check if charging allowed by system
                    df[power.name+'_to_'+storage.name+'_MWh'] = 0

        for storage in storage_systems:
            if operation == 'normal':
                start_storage = storage.capacity_MWh if storage.start_full else 0
            elif operation == 'off_grid':
                pass
            
            df[storage.name+'_MWh'] = start_storage
            df.loc[1:,storage.name+'_MWh'] = 0 # reset after first hour

            df[storage.name+'_to_load_MWh'] = 0
            df[storage.name+'_loss_MWh'] = 0

        #initializing site variables:
        sites_poi = {}
        for site in self.sites:
            df[site.name+'_POI_MW'] = 0
            sites_poi[site] = 0
            
        return storage_systems, power_systems, df  
        
    def operation(self, operation='normal', critical_load_MW = None, target_hours = None, df_res = None, res_initial = None):

        if operation == 'normal':
            #setting up operation type and timeseries
            storage_systems, power_systems, df = self.initialize_df(operation)
        elif operation == 'off_grid':
            storage_systems, power_systems, df = self.initialize_df(operation, critical_load_MW = critical_load_MW, target_hours = target_hours, df_res = df_res, res_initial = res_initial)
            to_end = 0
            recorded_lasthour = False
            endseries = df.index[-1]
        
        #looping through timeseries
        year_val = len(df)/(24*365)
        sites_poi = {}
        
        for i in range(len(df)-1):
            if i == 6:
                pass

            e_sale_hour = i % 24

            #local variable to track load satisfaction
            unmet_load_MW = df.loc[i+1,'load_MW']
            unmet_target_load_MW = df['target_load_MW'].get(i+1,None)
            if self.target_load_MW is not None: 
                tgl_val = unmet_target_load_MW/self.load_factor - unmet_target_load_MW
            else:
                tgl_val = 0                  
            
            # storage loss
            for storage in storage_systems:               
                storage_conversion = storage.conversion_values[i] # accept timeseries                   
                storage_MWh = df.loc[i, storage.name+'_MWh'] #local variable to track charge from previous
                loss = storage_MWh*storage.percent_loss_daily/2400 #percent daily loss converted to fraction for hourly loss
                storage_MWh = max(storage_MWh - loss, 0) # update local variable with loss, ensure nonnegative
                df.loc[i+1,storage.name+'_MWh'] = storage_MWh
                df.loc[i+1,storage.name+'_loss_MWh'] = loss # losses for this timestep after csp charging contribution
                
                storage_charge_power_remaining = storage.charge_rate_MW            
                storage_cols = []  
                for number, power in enumerate(power_systems):
                    #ensures each power system is checked for charging each storage
                    if power.name not in storage.systems_charging: 
                        continue

                    # tracking in loop, updated end of loop   
                    power_remaining = df.loc[i+1,power.name+'_power_MW']             
                    headroom_storage = storage.capacity_MWh - storage_MWh
                    power2storage = max(0,min([val for val in [storage_charge_power_remaining, power_remaining, headroom_storage/storage.charge_efficiency[number]] if val is not None]))
                    power_remaining -= power2storage
                    storage_MWh += power2storage * storage.charge_efficiency[number]

                    if storage_charge_power_remaining is not None:
                        storage_charge_power_remaining -= power2storage

                    df.loc[i+1,power.name+'_to_'+storage.name+'_MWh'] = power2storage
                    storage_cols.append(power.name+'_to_'+storage.name+'_MWh')       
                    df.loc[i+1,power.name+'_power_MW'] = power_remaining # tracking power after charging

                # updated storage charge at this timestep after charging by all power
                df.loc[i+1,storage.name+'_MWh'] = storage_MWh
                if len(storage_cols)>0:
                    df.loc[i+1,power.__class__.__name__+'_to_'+storage.name+'_MWh'] = sum([df.loc[i+1,c] for c in storage_cols])

            #power type gen, to energy_type storage, for charging not baseload
            for storage in storage_systems:
                # input power_type, output energy_type for generation to storage, in both generation, storage
                # function for dispatch, treat baseload as dispatch
                # dispatch - power leaves system, not to storage
                if storage.baseload == True:  #power type of generation used, find corresponding efficeingy, gen to storage                  
                    p_eff = 1              
                    storage_conversion = storage_conversion * p_eff # generic conversion variable
                    storage_MWh = df.loc[i+1, storage.name+'_MWh']

                    if storage.site.POI_limit is not None:
                        poi_remaining = storage.site.POI_limit - df.loc[i+1, storage.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf

                    # how much storage MWh are available for use, limited by discharge depth in normal operation
                    # storage_power_minimum ensures no power cycling for small loads in normal operation
                    if operation == 'normal':
                        storage_avail = max(0, storage_MWh - storage.capacity_MWh * (1. - storage.percent_discharge_depth / 100.))
                        storage_power_minimum = storage.power_minimum_MW
                    elif operation == 'off_grid':
                        storage_avail = max(0, storage_MWh)
                        storage_power_minimum = 0  # no minimum in off-grid operation

                    #storage_avail = max(0, storage_MWh) #temp for bes change
                    storage2load = 0

                    # Check if unmet_load_MW is greater than or equal to storage_power_minimum
                    if unmet_load_MW >= storage_power_minimum:
                        if unmet_target_load_MW is None or unmet_target_load_MW >= storage_power_minimum:
                            storage2load = min([val / storage_conversion for val in [storage_avail * storage_conversion, unmet_load_MW, unmet_target_load_MW, storage.power_rating_MW, poi_remaining] if val is not None])
                        elif unmet_target_load_MW < storage_power_minimum:
                            # supposed to pull from another battery storage
                            # I think unneeded

                            # total_batt_avail = sum([max([0, min([val for val in [df.loc[i + 1, storage.name + '_MWh'] * storage.discharge_efficiency, storage.power_rating_MW] if val is not None])]) for storage in storage_systems])
                            # if total_batt_avail >= unmet_target_load_MW:
                            #     storage2load = 0
                            # else:
                            #     storage2load = min([val / storage_conversion for val in [storage_avail * storage_conversion, unmet_load_MW, storage.power_rating_MW, poi_remaining] if val is not None])
                            
                            storage2load = min([val / storage_conversion for val in [storage_avail * storage_conversion, unmet_load_MW, storage.power_rating_MW, poi_remaining] if val is not None])

                    storage_MWh -= storage2load
                    unmet_load_MW -= storage2load * storage_conversion

                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0, unmet_target_load_MW - ((storage2load * storage_conversion) - tgl_val))

                    poi_remaining -= storage2load * storage_conversion
                    power_avail = sum([df[power.name+'_power_MW'].get(i+1) for power in power_systems if power.name in storage.systems_charging])
                    
                    for number, power in enumerate(power_systems):               
                        if power.name not in storage.systems_charging:
                            continue

                        storage_power_headroom = max(0,min([val for val in [unmet_load_MW, storage.power_rating_MW, poi_remaining, power_avail * storage.charge_efficiency[number] * storage_conversion] if val is not None]))
                        if storage_power_headroom > 0:
                            power_total = storage_power_headroom / (storage.charge_efficiency[number] * storage_conversion)
                            # Tracking in loop, updated end of loop
                            power_remaining = df.loc[i+1, power.name+'_power_MW']
                            
                            # Amount of power transferred, limited by availability, charge rate, and storage headroom
                            power2storage = max(0, min([val for val in [power_remaining, power_total] if val is not None]))  # Check charge rate efficiency
                            
                            # power heat left over
                            power_remaining -= power2storage
                            power_total -= power2storage
                            
                            # power at this timestep
                            df.loc[i+1, power.name+'_to_'+storage.name+'_MWh'] += power2storage
                            storage_cols.append(power.name+'_to_'+storage.name+'_MWh')                            
                            df.loc[i+1, power.name+'_power_MW'] = power_remaining # Tracking remaining power heat after charging storage
    
                    if storage_power_headroom > 0:
                        unmet_load_MW -= storage_power_headroom
                        storage2load += storage_power_headroom / storage_conversion

                    df.loc[i+1, storage.name+'_MWh'] = storage_MWh
                    # tracking load contribution in thermal
                    df.loc[i+1, storage.name+'_to_load_MWh'] = storage2load * storage_conversion
                    df.loc[i+1, storage.site.name+'_POI_MW'] += storage2load * storage_conversion
            
            for site in self.sites:
                sites_poi[site.name] = df.loc[i, site.name+'_POI_MW']

            for number, power in enumerate(power_systems):
                if power.to_load == True:
                    power_remaining = df.loc[i+1, power.name+'_power_MW']
                    
                    if power.site.POI_limit != None:
                        poi_remaining = power.site.POI_limit - df.loc[i+1,power.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
                    power_poi=0

                    power2l = min([val for val in [unmet_load_MW, unmet_target_load_MW, power_remaining, power.power_priority_load_MW, power.site.POI_limit] if val is not None])

                    #power to load for this timestep
                    if power2l < 0:
                        power2l = 0
                    df.loc[i+1,power.name+'_to_load_MWh'] = power2l
                    
                    power_remaining -= power2l #updating local variable for pv availability
                    poi_remaining -= power2l
                    power_poi+= power2l
                    unmet_load_MW -= power2l#updating unmet load after pv contribution
                    
                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0, unmet_target_load_MW - power2l)

                    # bes and tes charging by pv exists
                    # find way to combine both
                    for storage in storage_systems: 
                        if power.name not in storage.systems_charging:
                            continue
                        #local variable to track bes charge, checks if charged by another pv system already

                        #potential change
                        # if df.loc[i+1, storage.name+'_MWh'] > df.loc[i,storage.name+'_MWh']:
                        #     storage_MWh = df.loc[i+1, storage.name+'_MWh']
                        #     delta_storage = df.loc[i+1, storage.name+'_MWh'] - df.loc[i, storage.name+'_MWh']
                        # else:
                        #     storage_MWh = df.loc[i,storage.name+'_MWh']
                        #     delta_storage = 0

                        loss = df.loc[i+1,storage.name+'_loss_MWh']
                        storage_MWh = df.loc[i+1, storage.name+'_MWh']
                        delta_storage = max(0, storage_MWh - (df.loc[i,storage.name+'_MWh'] - loss)) # + csp_cont?
                        # delta_storage = 0
                        headroom_storage = storage.capacity_MWh - storage_MWh   

                        if power.site.name != storage.site.name:
                            poi_lim = poi_remaining
                        else:
                            poi_lim = np.inf

                        #temp, figure out better val
                        #maybe storage_charge_res_remaining added or replaces storage.power_rating
                        #option for different charge, discharge rate
                        power2storage = min([val for val in [storage.power_rating_MW - delta_storage, headroom_storage/storage.charge_efficiency[number], power_remaining, poi_lim] if val is not None])                        
                        power_remaining -= power2storage
                        
                        if power.site.name != storage.site.name:
                            poi_remaining -= power2storage
                            df.loc[i+1,storage.site.name+'_POI_MW']-= power2storage
                            power_poi += power2storage

                        df.loc[i+1, storage.name+'_MWh'] = storage_MWh + power2storage*storage.charge_efficiency[number] 
                        df.loc[i+1,power.name+'_to_'+storage.name+'_MWh'] = power2storage #tracking contribution
                        storage_MWh +=  power2storage * storage.charge_efficiency[number] #storage at this time step after charging contributions
                        df.loc[i+1, storage.name+'_MWh'] = storage_MWh

                    if power_remaining>0:
                        power2l2 = max(0,min(unmet_load_MW, power_remaining, poi_remaining))
                        unmet_load_MW -= power2l2
                        power_remaining -= power2l2
                        poi_remaining -= power2l2
                        power_poi += power2l2
                        df.loc[i+1,power.name+'_to_load_MWh'] = df.loc[i+1,power.name+'_to_load_MWh'] + power2l2
    
                    #pv after all has been directed to pv, bes, or tes
                    df.loc[i+1,power.name+'_to_grid_MWh'] = min(power_remaining,max(0,poi_remaining))
                    df.loc[i+1,power.name+'_curtailed_MWh'] = max(0,power_remaining)
                    df.loc[i+1,power.site.name+'_POI_MW'] = power_poi

                else:
                    #local variable to track power remaining
                    power_remaining = df.loc[i+1, power.name+'_power_MW']
                    if power.site.POI_limit != None:
                        poi_remaining = power.site.POI_limit - df.loc[i+1,power.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf

                    power_poi=0

                    # charging with pv
                    for storage in storage_systems: 
                        # check if power is allowed to charge storage
                        if power.name not in storage.systems_charging:
                            continue

                        loss = df.loc[i+1, storage.name+'_loss_MWh']
                        storage_MWh = df.loc[i+1, storage.name+'_MWh']
                        delta_storage = max(0, storage_MWh - (df.loc[i,storage.name+'_MWh'] - loss))
                        headroom_storage = storage.capacity_MWh - storage_MWh #calculate unused bes capacity

                        #calculate power contribution to storage, limited by storage charge rate, power remaining, and headroom
                        if power.site.name != storage.site.name:
                            poi_lim = poi_remaining
                        else:
                            poi_lim = np.inf

                        # temp for running
                        power2storage = min([val for val in [storage.power_rating_MW - delta_storage, headroom_storage/storage.charge_efficiency[number], power_remaining, poi_lim] if val is not None])
                        power_remaining -= power2storage #update local variable for pv availability, tracking 

                        # tracking poi contributions
                        if power.site.name != storage.site.name:
                            poi_remaining -= power2storage
                            df.loc[i+1,storage.site.name+'_POI_MW']-= power2storage
                            power_poi += power2storage

                        df.loc[i+1, storage.name+'_MWh'] = storage_MWh+ power2storage*storage.charge_efficiency[number]

                        #tracking contribution
                        df.loc[i+1,power.name+'_to_'+storage.name+'_MWh'] = power2storage
                        storage_MWh +=  power2storage * storage.charge_efficiency[number]
                        df.loc[i+1, storage.name+'_MWh'] = storage_MWh
    
                    # power after all has been directed to storage
                    df.loc[i+1,power.name+'_to_grid_MWh'] = min(power_remaining,max(0,poi_remaining))
                    df.loc[i+1,power.name+'_curtailed_MWh'] = max(0,power_remaining)
                    df.loc[i+1,power.site.name+'_POI_MW'] = power_poi

            for storage in storage_systems:
                if storage.baseload == False:
                    p_eff = 1
                    storage_conversion = storage_conversion * p_eff
                    storage_MWh = df.loc[i+1, storage.name+'_MWh'] # local variable to track storage charge state

                    if storage.site.POI_limit is not None:
                        poi_remaining = storage.site.POI_limit - df.loc[i+1, storage.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf

                    #how much storage MWh_t are available for use, limited by discharge depth in normal operation
                    # storage_power_minimum ensures no power cycling for small loads in normal operation
                    if operation == 'normal':
                        storage_avail = max(0, storage_MWh - storage.capacity_MWh * (1. - storage.percent_discharge_depth / 100.))
                        storage_power_minimum = storage.power_minimum_MW
                    elif operation == 'off_grid':
                        storage_avail = max(0, storage_MWh)
                        storage_power_minimum = 0  # no minimum in off-grid operation
               
                    #storage_avail = max(0, storage_MWh) # line for bes change
                    storage2load = 0

                    # Check if unmet_load_MW is greater than or equal to
                    # uses tes and bes for if-elif, how to resolve?
                    if unmet_load_MW >= storage_power_minimum:
                        if unmet_target_load_MW is None or unmet_target_load_MW >= storage_power_minimum:
                            storage2load = min([val / storage_conversion for val in [storage_avail * storage_conversion, unmet_load_MW, unmet_target_load_MW, storage.power_rating_MW, poi_remaining] if val is not None])
                        elif unmet_target_load_MW < storage_power_minimum:
                            storage2load = min([val / storage_conversion for val in [storage_avail * storage_conversion, unmet_load_MW, storage.power_rating_MW, poi_remaining] if val is not None])

                    storage_MWh -= storage2load
                    unmet_load_MW -= storage2load * storage_conversion

                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0, unmet_target_load_MW - ((storage2load * storage_conversion) - tgl_val))

                    poi_remaining -= storage2load * storage_conversion
                    power_avail = sum([df[power.name+'_power_MW'].get(i+1) for power in power_systems if power.name in storage.systems_charging])

                    for number, power in enumerate(power_systems):
                        # Ensures each power system is checked for charging each storage
                        if power.name not in storage.systems_charging:
                                continue

                        storage_power_headroom = max(0,min([val for val in [unmet_load_MW, storage.power_rating_MW, poi_remaining, power_avail * storage.charge_efficiency[number] * storage_conversion] if val is not None]))
                        if storage_power_headroom > 0:    
                            power_total = storage_power_headroom / (storage.charge_efficiency[number] * storage_conversion)

                            # Tracking in loop, updated end of loop
                            power_remaining = df.loc[i+1, power.name+'_power_MW']
                            
                            # Amount of power heat transferred, limited by availability, charge rate, and storage headroom
                            power2storage = max(0, min([val for val in [power_remaining, power_total] if val is not None]))  # Check charge rate efficiency
                            
                            # power heat left over
                            power_remaining -= power2storage
                            power_total -= power2storage
                            
                            storage_cols.append(power.name+'_to_'+storage.name+'_MWh')

                    df.loc[i+1, storage.name+'_MWh'] = storage_MWh
                    # tracking load contribution
                    df.loc[i+1, storage.name+'_to_load_MWh'] = storage2load * storage_conversion
                    df.loc[i+1, storage.site.name+'_POI_MW'] += storage2load * storage_conversion
                else:
                    df.loc[i+1, storage.site.name+'_POI_MW'] += sites_poi[storage.site.name]
                    
            #after storage and power, any unmet load satisfied by the grid
            df.loc[i+1,'grid_to_load_MWh_e'] = unmet_load_MW
            df.loc[i+1,'unmet_load_MWh_e'] = unmet_load_MW
            valb = (df.loc[i+1,'load_MW'] - unmet_load_MW) * self.e_sale * self.e_sale_factors[e_sale_hour] * 1000
            df.loc[i+1,'electricity_sale_in_hour'] = valb
            df.loc[i+1,'unmet_target_load_MWh_e'] = unmet_target_load_MW
            
            if self.target_load_MW is not None:
                df.loc[i+1,'export_energy_MWh_e'] = max(0,(df.loc[i+1,'load_MW'] - unmet_load_MW)-df.loc[i+1,'target_load_MW']) # this doesn't make sense to me, is this export potential? LUKE: YES, this is export potential above and beyond the target load. 

            if operation=='off_grid':
                if unmet_load_MW>0:

                    lasthour=i

                    if not recorded_lasthour:
                        lasthour=i
                        recorded_lasthour = True
                    if target_hours is None:
                        break
                    elif i >= target_hours:
                        break

                elif i+1==endseries:
                    lasthour=i+1
                    to_end=1
                    break

        if target_hours is not None:
            target_df = df.head(min(target_hours,len(df)))
            total_load=target_df.load_MW.sum()
            pct_target_energy = (total_load-target_df.unmet_load_MWh_e.sum())/total_load
            target_energy = target_df.unmet_load_MWh_e.sum()
        else:
            pct_target_energy = None
            target_energy = None

        
        df.set_index(self.load_MW.index.name,inplace=True)

        if operation=='normal':
            return df
        elif operation=='off_grid':

            return lasthour, to_end, pct_target_energy, target_energy
