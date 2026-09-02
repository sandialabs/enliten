# tes changes for testing
# start_tes = tes.capacity_MWh_t -> start_tes = tes.capacity_MWh_e
# tes_avail = max(0, tes_MWh_t - tes.capacity_MWh_t * (1. - tes.percent_discharge_depth / 100.))
# ->
# tes_avail = max(0, tes_MWh_t - tes.capacity_MWh_e * (1. - tes.percent_discharge_depth / 100.))

# tes changes for different test cases
# self.tes_baseload == False:
# self.tes_baseload == True:
# self.metrics = self.system_metrics()
# ts = csp.pah
# self.time_series
# tes_baseload = False -> tes_baseload = True

# bes changes

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

    
 # Constant TEA PARAMETERS
tax = 0.257 # [frac] State and federal tax rate (ASGARD BASELINE)
inflation = 0.028 # [frac] Inflation rate
insurance = 0.004   #[frac] Insurance rate
property_tax = 0.0084 # [frac] Property Tax Rate
depreciation_period = 5 # [yrs] MACRS Depreciation Period 
esc = 0.028 # [frac] Escalation rate  

# Fuel Cost (default Natural Gas)
gas_cost_months = np.array([7.15, 7.04, 5.8, 4.42, 3.06, 2.75, 3.76, 4.24, 3.88, 5.03, 5.63, 6.37])# [$/MMBtu] 
days_in_month = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
hours_in_month = days_in_month * 24
gas_cost = np.concatenate([np.full(hours, price) for hours, price in zip(hours_in_month, gas_cost_months)])
t2e_gas = 1.0 # Gas cycle efficiency when solely gas source
eta_cc = 0.9 # Combustion chamber efficiency
LHV_gas = 4.6e4 # LHV [kJ/kg]
kg2mmbtu = 0.0437 # kg to MMBTU using LHV

# # Fuel Cost (RFO)
# gas_cost_months = np.array([9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5])# [$/MMBtu] 
# days_in_month = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
# hours_in_month = days_in_month * 24
# gas_cost = np.concatenate([np.full(hours, price) for hours, price in zip(hours_in_month, gas_cost_months)])
# t2e_gas = 1.0 # Gas cycle efficiency when solely gas source
# eta_cc = 0.9 # Combustion chamber efficiency
# LHV_gas = 4.0e4 # LHV [kJ/kg]
# kg2mmbtu = 0.038


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
    
    def __init__(self, load_MW, systems_load_order, analysis_period = 30, ITC = 0.5, DF = 0.5, I = 0.08, COE = 0.13, grant_pct = 0, e_sale = 0.07, e_sale_factors = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1], VOM = 0.003, load_factor = 1, target_load_MW=None, tes_baseload = False, pv_to_load = True, tes_gasbackup = False, sell_export = False, custom_financing = False, total_project_cost = False):
        # self.time_series = time_series
        self.load_MW = load_MW
        self.systems = systems_load_order
        self.system_names = [sys.name for sys in self.systems]
        self.sites = list(set([sys.site for sys in self.systems]))
        self.analysis_period = analysis_period
        self.ITC = ITC
        self.DF = DF
        self.I = I
        self.COE = COE
        self.grant_percentage = grant_pct
        self.target_load_MW = target_load_MW
        self.tes_baseload = False
        self.pv_to_load = True
        self.tes_gasbackup = tes_gasbackup
        self.sell_export = sell_export
        self.custom_financing = custom_financing
        self.total_project_cost = total_project_cost
        self.e_sale = e_sale
        self.e_sale_factors = e_sale_factors
        self.VOM = VOM
        self.load_factor = load_factor
        self.gas_cost = gas_cost
        self.t2e_gas = t2e_gas

        #separating systems by type
        self.pv_systems = [sys for sys in self.systems if isinstance(sys,PV_System)]
        self.csp_systems = [sys for sys in self.systems if isinstance(sys,CSP_System)]
        self.bes_systems = [sys for sys in self.systems if isinstance(sys,BES_System)]
        self.tes_systems = [sys for sys in self.systems if isinstance(sys,TES_System)]

        #defining off-grid systems
        self.off_grid_systems = [sys for sys in self.systems if sys.off_grid_operation==True]

        self.pv_systems_off_grid = [sys for sys in self.off_grid_systems if isinstance(sys,PV_System)]
        self.csp_systems_off_grid = [sys for sys in self.off_grid_systems if isinstance(sys,CSP_System)]
        self.bes_systems_off_grid = [sys for sys in self.off_grid_systems if isinstance(sys,BES_System)]
        self.tes_systems_off_grid = [sys for sys in self.off_grid_systems if isinstance(sys,TES_System)]

        #saving pv power to system variable
        for sys in self.pv_systems:
            setattr(self, sys.name, sys.power_timeseries.copy().reset_index(inplace=True))

        #saving csp heat to system variables
        for csp in self.csp_systems:
            setattr(self, csp.name, csp.pah)
        
        self.timeseries = self.operation()

        #determination of TES and BES power ratings and capex if set to None

        for tes in self.tes_systems:
            if tes.charge_rate_resistive_MW_e is None:
                pv_cols=[]
                for sys in self.pv_systems:#tes.systems_charging:
                    if sys.name in tes.systems_charging:# sys.__class__.__name__==self.pv_systems[0].__class__.__name__:
                        pv_cols.append(sys.name)
                pv_cols = [pv_name+'_to_'+tes.name+'_MWh_e' for pv_name in pv_cols]
                tmax = self.timeseries[pv_cols].sum(axis=1).max()
                tes.charge_rate_resistive_MW_e = tmax
                
            if tes.charge_rate_CSP_MW_t is None:
                thmax=self.timeseries[self.csp_systems[0].__class__.__name__+'_to_'+tes.name+'_MWh_t'].max()
                tes.charge_rate_CSP_MW_t = thmax
                    
            if tes.capex_USD is None:
                tes.capex_USD = tes.calculate_capex(tmax,40.84, 125,15.625)
                tes.cpx_htr_aug_annual=tes.calculate_htr_aug(tmax)

        for bes in self.bes_systems:
            if bes.power_rating_MW_e is None:
                pv_cols=[]
                for sys in self.pv_systems:#bes.systems_charging:
                    if sys.name in bes.systems_charging:
                        pv_cols.append(sys.name)
                pv_cols = [pv_name+'_to_'+bes.name+'_MWh_e' for pv_name in pv_cols]
                cmax = self.timeseries[pv_cols].sum(axis=1).max()
                bmax = max(self.timeseries[bes.name+'_to_load_MWh_e'].max(),cmax)
                bes.power_rating_MW_e = bmax
                bes.capex_USD = bes.capex_calc(bmax)

        # self.metrics = self.system_metrics()

    def operational_systems(self, operation):
        if operation=='normal':
            pv_systems = self.pv_systems
            csp_systems = self.csp_systems
            bes_systems = self.bes_systems
            tes_systems = self.tes_systems

        elif operation=='off_grid':
            pv_systems = self.pv_systems_off_grid
            csp_systems = self.csp_systems_off_grid
            bes_systems = self.bes_systems_off_grid
            tes_systems = self.tes_systems_off_grid
        
        return pv_systems, csp_systems, bes_systems, tes_systems
        

    def initialize_df(self, operation='normal', critical_load_MW = None, target_hours = None, df_res = None, res_initial = None):

        #determining which systems are being used (dynamic for off-grid scenario)
        pv_systems, csp_systems, bes_systems, tes_systems = self.operational_systems(operation)

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

        #initialize pv system power values and flows
        for pv in pv_systems:
            if operation == 'normal':
                ts = pv.power_timeseries.power_MW_AC.values
            elif operation == 'off_grid':
                ts = df_res[pv.name+'_power_MW_AC'].values
            #matching pv power series length to load length
            if len(ts)>=numrec:
                ts = ts[:numrec] #truncate if power timeseries is longer than load timeseries
            elif len(ts)<numrec:
                ts = list(islice(cycle(ts), numrec)) #repeat power timeseries if shorter than load timeseries
            df[pv.name+'_power_MW_AC'] = ts

            df[pv.name+'_to_load_MWh_e'] = 0
            df[pv.name+'_to_grid_MWh_e'] = 0
            df[pv.name+'_curtailed_MWh_e'] = 0

            #initialize charging of bes by pv
            for bes in bes_systems:
                if pv.name in bes.systems_charging: #check if charging allowed by pv system
                    df[pv.name+'_to_'+bes.name+'_MWh_e'] = 0

            #initialize charging of tes by pv
            for tes in tes_systems:
                df[pv.name+'_to_'+tes.name+'_MWh_e'] = 0

        #initializing bes variables based on system parameters
        for bes in bes_systems:
            if operation == 'normal':
                #initializing BES full or empty
                if bes.start_full:
                    start_bes = bes.capacity_MWh_e
                elif not bes.start_full:
                    start_bes = 0
            elif operation == 'off_grid':
                if res_initial == 'actual':
                    start_bes = df_res[bes.name+'_MWh_DC'].values[0]
                elif res_initial == 'full':
                    start_bes = bes.capacity_MWh_e
            df[bes.name+'_MWh_DC'] = start_bes
            df.loc[1:,bes.name+'_MWh_DC'] = 0

            df[bes.name+'_to_load_MWh_e'] = 0

        #initializing csp variables
        for csp in self.csp_systems:
            if operation == 'normal':
                ts = csp.pah
                # ts = self.time_series
            elif operation == 'off_grid':
                ts = df_res[csp.name+'_heat_MW_t'].values
            #matching csp ts length to load length
            if len(ts)>=numrec:
                ts = ts[:numrec] #truncate if power timeseries is longer than load timeseries
            elif len(ts)<numrec:
                ts = list(islice(cycle(ts), numrec)) #repeat power timeseries if shorter than load timeseries
            df[csp.name+'_heat_MW_t'] = ts
            df[csp.name+'_heat_unused_MWh_t'] = ts

            #initializing power flow csp -> tes
            for tes in self.tes_systems:
                if csp.name in tes.systems_charging:
                    df[csp.name+'_to_'+tes.name+'_MWh_t'] = 0

        #initializing tes variables
        for tes in tes_systems:
            if operation == 'normal':
                #initializing TES full or empty
                if tes.start_full: #change to variable starting capacity?
                    start_tes = tes.capacity_MWh_e
                elif not tes.start_full:
                    start_tes = 0
            elif operation == 'off_grid':
                if res_initial == 'actual':
                    start_tes = df_res[tes.name+'_MWh_t'].values[0]
                elif res_initial == 'full':
                    start_tes = tes.capacity_MWh_t
            df[tes.name+'_MWh_t'] = start_tes
            df.loc[1:,tes.name+'_MWh_t'] = 0
            df[tes.name+'_thermal_loss_MWh_t'] = 0

            if len(self.csp_systems)>0:
                df[csp_systems[0].__class__.__name__+'_to_'+tes.name+'_MWh_t']=0

            df[tes.name+'_to_load_MWh_t'] = 0
            df[tes.name+'_to_load_MWh_e'] = 0

            df[tes.name+'_to_load_MWh_gas_e'] = 0
            df[tes.name+'_to_load_MWh_gas_t'] = 0
            df[tes.name+'_to_load_MWh_gas_kg'] = 0
            df[tes.name+'_gas_dollars'] = 0
            df[tes.name+'_frac_nogas'] = 0
            df[tes.name+'_frac_gas'] = 0

        #initializing site variables:
        for site in self.sites:
            df[site.name+'_POI_MW'] = 0
        
        return pv_systems, csp_systems, bes_systems, tes_systems, df

    def operation(self, operation='normal', critical_load_MW = None, target_hours = None, df_res = None, res_initial = None):

        if operation == 'normal':
            #setting up operation type and timeseries
            pv_systems, csp_systems, bes_systems, tes_systems, df = self.initialize_df(operation)
        elif operation == 'off_grid':
            pv_systems, csp_systems, bes_systems, tes_systems, df = self.initialize_df(operation, critical_load_MW = critical_load_MW, target_hours = target_hours, df_res = df_res, res_initial = res_initial)
            to_end = 0
            recorded_lasthour = False
            endseries = df.index[-1]
        
        #looping through timeseries
        year_val = len(df)/(24*365)
        gas_cost = np.tile(self.gas_cost, int(year_val))

        print(len(gas_cost))
        
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
            
            #tes heat losses first
            for tes in tes_systems:
                tes_t2e = tes.t2e_values[i]
                #local variable to track charge from previous
                tes_MWh_t = df.loc[i, tes.name+'_MWh_t']
                #percent daily loss converted to fraction for hourly loss
                tloss = tes_MWh_t*tes.percent_heat_loss_daily/2400
                #update local variable with thermal loss, ensure nonnegative
                tes_MWh_t = max(tes_MWh_t-tloss,0)
                df.loc[i+1,tes.name+'_MWh_t'] = tes_MWh_t
                #thermal losses for this timestep after csp charging contribution
                df.loc[i+1,tes.name+'_thermal_loss_MWh_t'] = tloss

                tes_charge_csp_remaining = tes.charge_rate_CSP_MW_t
                tes_cols = []

                for csp in csp_systems:
                    #ensures each csp system is checked for charging each tes
                    if csp.name not in tes.systems_charging:
                        continue
                    #tracking in loop, updated end of loop
                    csp_remaining = df.loc[i+1,csp.name+'_heat_unused_MWh_t']
                    #amount of csp heat transferred. limited by availability, charge rate, and tes headroom

                    #calculating tes headroom
                    headroom_tes = tes.capacity_MWh_t-tes_MWh_t
                    
                    csp2tes = max(0,min([val for val in [tes_charge_csp_remaining, csp_remaining, headroom_tes/tes.charge_efficiency_t2TES] if val is not None])) #check charge rate efficiency

                    #csp heal left over
                    csp_remaining -= csp2tes
                    
                    #local tes variable updated with heat transfer scaled by charging efficiency
                    tes_MWh_t += csp2tes*tes.charge_efficiency_t2TES

                    #tracking charge_csp_remaining
                    if tes_charge_csp_remaining is not None:
                        tes_charge_csp_remaining -= csp2tes
                    
                    #csp heat at this timestep
                    df.loc[i+1,csp.name+'_to_'+tes.name+'_MWh_t'] = csp2tes
                    tes_cols.append(csp.name+'_to_'+tes.name+'_MWh_t')
                    
                    #tracking remaining csp heat after charging TES
                    df.loc[i+1,csp.name+'_heat_unused_MWh_t'] = csp_remaining
                    
                #updated tes charge at this timestep after charging by all csp
                df.loc[i+1,tes.name+'_MWh_t'] = tes_MWh_t
                if len(tes_cols)>0:
                    df.loc[i+1,csp.__class__.__name__+'_to_'+tes.name+'_MWh_t'] = sum([df.loc[i+1,c] for c in tes_cols])

            # TES to load first if tes_baseload == True
            if self.tes_baseload == True:
                # p_eff = 1
                # tes_t2e = tes_t2e * p_eff
                # t2e_gas = self.t2e_gas * p_eff
                for tes in tes_systems:
                    p_eff = 1
                    tes_t2e = tes_t2e * p_eff
                    t2e_gas = self.t2e_gas * p_eff
                    # local variable to track tes charge state
                    tes_MWh_t = df.loc[i+1, tes.name+'_MWh_t']
                
                    if tes.site.POI_limit is not None:
                        poi_remaining = tes.site.POI_limit - df.loc[i+1, tes.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
            
                    # how much tes MWh_t are available for use, limited by discharge depth in normal operation
                    if operation == 'normal':
                        tes_avail = max(0, tes_MWh_t - tes.capacity_MWh_e * (1. - tes.percent_discharge_depth / 100.))
                    elif operation == 'off_grid':
                        tes_avail = max(0, tes_MWh_t)
                    # how much tes MWh_e are available for use
                    tes_avail_e = tes_avail * tes_t2e
            
                    # tes_power_minimum ensures no power cycling for small loads in normal operation
                    if operation == 'normal':
                        tes_power_minimum = tes.power_minimum_MW_e
                    elif operation == 'off_grid':
                        tes_power_minimum = 0  # no minimum in off-grid operation
            
                    tes2load = 0
                    gas2load_e = 0
                    gas2load = 0
                    mass2load = 0
                    gasprice2load = 0
            
                    # Check if unmet_load_MW is greater than or equal to tes_power_minimum
                    if unmet_load_MW >= tes_power_minimum:
                        if self.tes_gasbackup == True:
                            tes2load_e = min([val for val in [unmet_load_MW, unmet_target_load_MW, tes.power_rating_MW_e, poi_remaining] if val is not None])
                            if tes_avail_e >= tes2load_e:
                                tes2load = tes2load_e / tes_t2e
                                gas2load_e = (tgl_val)
                            else:
                                gas2load_e = (tes2load_e - tes_avail_e) + tgl_val
                                gas2load = gas2load_e / t2e_gas / eta_cc 
                                mass2load = (gas2load * 3.6e6) / LHV_gas 
                                gasprice2load = mass2load * kg2mmbtu * gas_cost[i]
                                tes2load = tes_avail_e / tes_t2e
                        else:
                            if unmet_target_load_MW is None or unmet_target_load_MW >= tes_power_minimum:
                                tes2load = min([val / tes_t2e for val in [tes_avail * tes_t2e, unmet_load_MW, unmet_target_load_MW, tes.power_rating_MW_e, poi_remaining] if val is not None])
                            elif unmet_target_load_MW < tes_power_minimum:
                                total_batt_avail = sum([max([0, min([val for val in [df.loc[i + 1, bes.name + '_MWh_DC'] * bes.discharge_efficiency, bes.power_rating_MW_e] if val is not None])]) for bes in bes_systems])
                                if total_batt_avail >= unmet_target_load_MW:
                                    tes2load = 0
                                else:
                                    tes2load = min([val / tes_t2e for val in [tes_avail * tes_t2e, unmet_load_MW, tes.power_rating_MW_e, poi_remaining] if val is not None])
            
                    tes_frac_gas = (tes2load * tes_t2e + gas2load_e) / tes.power_rating_MW_e
                    tes_frac_nogas = (tes2load * tes_t2e) / tes.power_rating_MW_e
            
                    tes_MWh_t -= tes2load
                    unmet_load_MW -= (tes2load * tes_t2e) + gas2load_e 
            
                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0, unmet_target_load_MW - ((tes2load * tes_t2e) + gas2load_e - tgl_val))
            
                    poi_remaining -= tes2load * tes_t2e

                    csp_avail = sum([df[csp.name + '_heat_unused_MWh_t'].get(i + 1) for csp in csp_systems if csp.name in tes.systems_charging])
    
                    tes_power_headroom = max(0,min([val for val in [unmet_load_MW, tes.power_rating_MW_e, poi_remaining, csp_avail * tes.charge_efficiency_t2TES * tes_t2e] if val is not None]))
                    if tes_power_headroom > 0:
                        csp_total = tes_power_headroom / (tes.charge_efficiency_t2TES * tes_t2e)
                        for csp in csp_systems:
                            # Ensures each CSP system is checked for charging each TES
                            if csp.name not in tes.systems_charging:
                                continue
                            
                            # Tracking in loop, updated end of loop
                            csp_remaining = df.loc[i + 1, csp.name + '_heat_unused_MWh_t']
                            
                            # Amount of CSP heat transferred, limited by availability, charge rate, and TES headroom
                            csp2tes = max(0, min([val for val in [csp_remaining, csp_total] if val is not None]))  # Check charge rate efficiency
                            
                            # CSP heat left over
                            csp_remaining -= csp2tes
                            csp_total -= csp2tes
                            
                            # CSP heat at this timestep
                            df.loc[i + 1, csp.name + '_to_' + tes.name + '_MWh_t'] += csp2tes
                            tes_cols.append(csp.name + '_to_' + tes.name + '_MWh_t')
                            
                            # Tracking remaining CSP heat after charging TES
                            df.loc[i + 1, csp.name + '_heat_unused_MWh_t'] = csp_remaining
    
                        unmet_load_MW -= tes_power_headroom
                        tes2load += tes_power_headroom/tes_t2e
            
                    # updating tes at this timestamp after load contribution
                    df.loc[i+1, tes.name+'_MWh_t'] = tes_MWh_t
                    # tracking load contribution in thermal
                    df.loc[i+1, tes.name+'_to_load_MWh_t'] = tes2load
                    # tracking load contribution in gas backup
                    df.loc[i+1, tes.name+'_to_load_MWh_gas_e'] = gas2load_e
                    # tracking thermal load contribution in gas backup
                    df.loc[i+1, tes.name+'_to_load_MWh_gas_t'] = gas2load
                    # tracking fuel mass contribution in gas backup 
                    df.loc[i+1, tes.name+'_to_load_MWh_gas_kg'] = mass2load
                    df.loc[i+1, tes.name+'_gas_dollars'] = gasprice2load
                    # tracking operational fraction power block
                    df.loc[i+1, tes.name+'_frac_nogas'] = tes_frac_nogas
                    df.loc[i+1, tes.name+'_frac_gas'] = tes_frac_gas
                    # tracking load contribution in electrical
                    df.loc[i+1, tes.name+'_to_load_MWh_e'] = tes2load * tes_t2e
                    # tracking poi_limit
                    df.loc[i+1, tes.site.name+'_POI_MW'] += tes2load * tes_t2e
            
            #next allocating pv power (first if tes_baseload == False)
            if self.pv_to_load == True:
                for pv in pv_systems:
                    #local variable to track pv power remaining
                    pv_remaining = df.loc[i+1, pv.name+'_power_MW_AC']
                    #local variable to track site POI
                    if pv.site.POI_limit != None:
                        poi_remaining = pv.site.POI_limit - df.loc[i+1,pv.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
                    pv_poi=0
                    #pv to load, limited by unmet load, power available, and power limits (if directing to BES systems)
                    pv2l = min([val for val in [unmet_load_MW, unmet_target_load_MW, pv_remaining, pv.power_priority_load_MW_AC, pv.site.POI_limit] if val is not None])
                    #pv to load for this timestep
                    if pv2l < 0:
                        pv2l = 0
                    df.loc[i+1,pv.name+'_to_load_MWh_e'] = pv2l
                    #updating local variable for pv availability
                    pv_remaining -= pv2l
                    poi_remaining -= pv2l
                    pv_poi+= pv2l
                    #updating unmet load after pv contribution
                    unmet_load_MW -= pv2l
                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0, unmet_target_load_MW - pv2l)
    
                    #battery charging with pv
                    for bes in bes_systems:
                        #check if pv is allowed to charge bes
                        if pv.name not in bes.systems_charging: 
                            continue
    
                        #local variable to track bes charge, checks if charged by another pv system already
                        if df.loc[i+1,bes.name+'_MWh_DC']>df.loc[i,bes.name+'_MWh_DC']:
                            bes_MWh = df.loc[i+1,bes.name+'_MWh_DC']
                            delta_bes = df.loc[i+1,bes.name+'_MWh_DC']-df.loc[i,bes.name+'_MWh_DC']
                        else:
                            bes_MWh = df.loc[i,bes.name+'_MWh_DC']
                            delta_bes=0
                        #calculate unused bes capacity
                        headroom_bes = bes.capacity_MWh_e - bes_MWh
    
                        #calculate pv contribution to battery, limited by bes charge rate, pv remaining, and headroom
                        if pv.site.name != bes.site.name:
                            poi_lim = poi_remaining
                        else:
                            poi_lim = np.inf
                        pv2batt = max(0,min([val-delta_bes for val in [bes.power_rating_MW_e, pv_remaining+delta_bes, poi_lim+delta_bes, (headroom_bes/bes.charge_efficiency)+delta_bes] if val is not None])) # assumes bes power rating = bes charge rating
                        #update local variable for pv availability, tracking 
                        pv_remaining -= pv2batt
                        if pv.site.name != bes.site.name:
                            poi_remaining -= pv2batt
                            df.loc[i+1,bes.site.name+'_POI_MW']-= pv2batt
                            pv_poi += pv2batt
    
                        #tracking pv contribution to bes
                        df.loc[i+1,pv.name+'_to_'+bes.name+'_MWh_e'] = pv2batt
                        #bes at this time step after charging contributions
                        df.loc[i+1,bes.name+'_MWh_DC'] = bes_MWh+pv2batt*bes.charge_efficiency
                        
                    #charging tes from pv after bes is satisfied
                    for tes in tes_systems:
                        #check if charging by pv is allowed
                        if pv.name not in tes.systems_charging:
                            continue
    
                        #local variable to track tes charge, from updated df variable, checking if updated for multiple charging sources
                        if len(csp_systems)>0:
                            csp_cont = df.loc[i+1,csp_systems[0].__class__.__name__+'_to_'+tes.name+'_MWh_t']
                        else:
                            csp_cont = 0
                        tloss = df.loc[i+1,tes.name+'_thermal_loss_MWh_t']
                        tes_MWh_t = df.loc[i+1,tes.name+'_MWh_t']
                        delta_tes = max(0, tes_MWh_t - (df.loc[i,tes.name+'_MWh_t'] - tloss + csp_cont))
    
                        if tes.charge_rate_resistive_MW_e is not None:
                            tes_charge_res_remaining = tes.charge_rate_resistive_MW_e - delta_tes
                        elif tes.charge_rate_resistive_MW_e is None:
                            tes_charge_res_remaining = None
                        
                        #recalculating tes headroom
                        headroom_tes = tes.capacity_MWh_t-tes_MWh_t
                        
                        #calculating pv contribution to tes, limited by charge rate, headroom, pv availability
                        if pv.site.name != tes.site.name:
                            poi_lim = poi_remaining
                        else:
                            poi_lim = np.inf
                        pv2tes = min([val for val in [tes_charge_res_remaining, headroom_tes/tes.charge_efficiency_e2TES, pv_remaining, poi_lim] if val is not None])
                        
                        #tracking pv contribution to tes
                        df.loc[i+1,pv.name+'_to_'+tes.name+'_MWh_e'] = pv2tes
    
                        #update pv still available
                        pv_remaining -= pv2tes
                        #tracking poi contributions
                        if pv.site.name != tes.site.name:
                            poi_remaining -= pv2tes
                            df.loc[i+1,tes.site.name+'_POI_MW']-= pv2tes
                            pv_poi += pv2tes
                        
                        #update tes charge state with pv scaled by efficiency
                        tes_MWh_t += pv2tes*tes.charge_efficiency_e2TES
                        #tes charge state at this timestep after csp and pv contributions
                        df.loc[i+1,tes.name+'_MWh_t'] = tes_MWh_t
    
                    #second chance pv to load if bes and/or TES is full
                    if pv_remaining>0:
                        pv2l2 = max(0,min(unmet_load_MW, pv_remaining, poi_remaining))
                        unmet_load_MW -= pv2l2
                        pv_remaining -= pv2l2
                        poi_remaining -= pv2l2
                        pv_poi += pv2l2
                        df.loc[i+1,pv.name+'_to_load_MWh_e'] = df.loc[i+1,pv.name+'_to_load_MWh_e'] + pv2l2
    
                    #pv after all has been directed to pv, bes, or tes
                    df.loc[i+1,pv.name+'_to_grid_MWh_e'] = min(pv_remaining,max(0,poi_remaining))
                    df.loc[i+1,pv.name+'_curtailed_MWh_e'] = max(0,pv_remaining)
                    df.loc[i+1,pv.site.name+'_POI_MW'] = pv_poi
            else:
                for pv in pv_systems:
                    #local variable to track pv power remaining
                    pv_remaining = df.loc[i+1, pv.name+'_power_MW_AC']
                    if pv.site.POI_limit != None:
                        poi_remaining = pv.site.POI_limit - df.loc[i+1,pv.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
                    pv_poi=0
    
                    #battery charging with pv
                    for bes in bes_systems:
                        #check if pv is allowed to charge bes
                        if pv.name not in bes.systems_charging: 
                            continue
    
                        #local variable to track bes charge, checks if charged by another pv system already
                        if df.loc[i+1,bes.name+'_MWh_DC']>df.loc[i,bes.name+'_MWh_DC']:
                            bes_MWh = df.loc[i+1,bes.name+'_MWh_DC']
                            delta_bes = df.loc[i+1,bes.name+'_MWh_DC']-df.loc[i,bes.name+'_MWh_DC']
                        else:
                            bes_MWh = df.loc[i,bes.name+'_MWh_DC']
                            delta_bes=0
                        #calculate unused bes capacity
                        headroom_bes = bes.capacity_MWh_e - bes_MWh
    
                        #calculate pv contribution to battery, limited by bes charge rate, pv remaining, and headroom
                        if pv.site.name != bes.site.name:
                            poi_lim = poi_remaining
                        else:
                            poi_lim = np.inf
                        pv2batt = max(0,min([val-delta_bes for val in [bes.power_rating_MW_e, pv_remaining+delta_bes, poi_lim+delta_bes, (headroom_bes/bes.charge_efficiency)+delta_bes] if val is not None])) # assumes bes power rating = bes charge rating
                        #update local variable for pv availability, tracking 
                        pv_remaining -= pv2batt
                        if pv.site.name != bes.site.name:
                            poi_remaining -= pv2batt
                            df.loc[i+1,bes.site.name+'_POI_MW']-= pv2batt
                            pv_poi += pv2batt
    
                        #tracking pv contribution to bes
                        df.loc[i+1,pv.name+'_to_'+bes.name+'_MWh_e'] = pv2batt
                        #bes at this time step after charging contributions
                        df.loc[i+1,bes.name+'_MWh_DC'] = bes_MWh+pv2batt*bes.charge_efficiency
                        
                    #charging tes from pv after bes is satisfied
                    for tes in tes_systems:
                        #check if charging by pv is allowed
                        if pv.name not in tes.systems_charging:
                            continue
    
                        #local variable to track tes charge, from updated df variable, checking if updated for multiple charging sources
                        if len(csp_systems)>0:
                            csp_cont = df.loc[i+1,csp_systems[0].__class__.__name__+'_to_'+tes.name+'_MWh_t']
                        else:
                            csp_cont = 0
                        tloss = df.loc[i+1,tes.name+'_thermal_loss_MWh_t']
                        tes_MWh_t = df.loc[i+1,tes.name+'_MWh_t']
                        delta_tes = max(0, tes_MWh_t - (df.loc[i,tes.name+'_MWh_t'] - tloss + csp_cont))
    
                        if tes.charge_rate_resistive_MW_e is not None:
                            tes_charge_res_remaining = tes.charge_rate_resistive_MW_e - delta_tes
                        elif tes.charge_rate_resistive_MW_e is None:
                            tes_charge_res_remaining = None
                        
                        #recalculating tes headroom
                        headroom_tes = tes.capacity_MWh_t-tes_MWh_t
                        
                        #calculating pv contribution to tes, limited by charge rate, headroom, pv availability
                        if pv.site.name != tes.site.name:
                            poi_lim = poi_remaining
                        else:
                            poi_lim = np.inf
                        pv2tes = min([val for val in [tes_charge_res_remaining, headroom_tes/tes.charge_efficiency_e2TES, pv_remaining, poi_lim] if val is not None])
                        
                        #tracking pv contribution to tes
                        df.loc[i+1,pv.name+'_to_'+tes.name+'_MWh_e'] = pv2tes
    
                        #update pv still available
                        pv_remaining -= pv2tes
                        #tracking poi contributions
                        if pv.site.name != tes.site.name:
                            poi_remaining -= pv2tes
                            df.loc[i+1,tes.site.name+'_POI_MW']-= pv2tes
                            pv_poi += pv2tes
                        
                        #update tes charge state with pv scaled by efficiency
                        tes_MWh_t += pv2tes*tes.charge_efficiency_e2TES
                        #tes charge state at this timestep after csp and pv contributions
                        df.loc[i+1,tes.name+'_MWh_t'] = tes_MWh_t
    
                    #pv after all has been directed to pv, bes, or tes
                    df.loc[i+1,pv.name+'_to_grid_MWh_e'] = min(pv_remaining,max(0,poi_remaining))
                    df.loc[i+1,pv.name+'_curtailed_MWh_e'] = max(0,pv_remaining)
                    df.loc[i+1,pv.site.name+'_POI_MW'] = pv_poi
                    

            # bes contributions to load are before TES if tes_gasbackup == True and tes_baseload == False
            if self.tes_gasbackup == True:
                for bes in bes_systems:
                    # rule for max_total_power
                    if (bes.max_total_power_MW is not None) and operation=='normal':
                        pvs, total = bes.max_total_power_MW
                        if not isinstance(pvs, list):
                            pvs = [pvs]
                        #calculate total power of all counted systems for that timestep
                        p = sum([df.loc[i+1,pv+'_to_load_MWh_e'] for pv in pvs])
                        #maximum bes contribution, ensure nonnegative
                        bes_max = max(0,total-p)
                    else:
                        bes_max = bes.power_rating_MW_e
                    #local variable to track bes charge state, updated with charging above
                    bes_MWh = df.loc[i+1,bes.name+'_MWh_DC']
                    # calculate bes available, limited by discharge depth, ensure nonnegative
                    if operation=='normal':
                        bes_avail = max(0,bes_MWh-bes.capacity_MWh_e*(1.-bes.percent_discharge_depth/100.))
                    elif operation=='off_grid':
                        bes_avail = max(0,bes_MWh) #comment out previous 3 lines to account for usable BES capacity 
                    #calculate bes available
                    bes_avail = max(0,bes_MWh) 

                    if bes.site.POI_limit is not None:
                        poi_remaining = bes.site.POI_limit - df.loc[i+1,bes.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
                    #calculating bes to load, limited by availability, unmet load, and bes power rating
                    bes2load = max([0,min([val/bes.discharge_efficiency for val in [bes_avail*bes.discharge_efficiency, unmet_load_MW, unmet_target_load_MW, bes_max, poi_remaining] if val is not None])])
                    #updating local variable for bes charge state
                    bes_MWh -= bes2load
                    #updating local variable to track unmet load
                    unmet_load_MW -= bes2load*bes.discharge_efficiency
                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0,unmet_target_load_MW - bes2load*bes.discharge_efficiency)
    
                    #bes charge state at this timestep
                    df.loc[i+1,bes.name+'_MWh_DC'] = bes_MWh
                    #tracking bes to load at this timestep
                    df.loc[i+1,bes.name+'_to_load_MWh_e'] = bes2load*bes.discharge_efficiency
                    #tracking poi
                    df.loc[i+1,bes.site.name+'_POI_MW'] += bes2load*bes.discharge_efficiency
            
            #load satisfaction by tes (Last if tes_gasbackup == True & tes_baseload == False, second to last behind BES if tes_gasbackup == False & tes_baseload == False)
            if self.tes_baseload == False:
                # moved for testing
                # p_eff = 1
                # tes_t2e = tes_t2e * p_eff
                # t2e_gas = self.t2e_gas * p_eff
                for tes in tes_systems:
                    p_eff = 1
                    tes_t2e = tes_t2e * p_eff
                    t2e_gas = self.t2e_gas * p_eff
                    # local variable to track tes charge state
                    tes_MWh_t = df.loc[i+1, tes.name+'_MWh_t']
                
                    if tes.site.POI_limit is not None:
                        poi_remaining = tes.site.POI_limit - df.loc[i+1, tes.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
            
                    # how much tes MWh_t are available for use, limited by discharge depth in normal operation
                    if operation == 'normal':
                        tes_avail = max(0, tes_MWh_t - tes.capacity_MWh_e * (1. - tes.percent_discharge_depth / 100.))

                    elif operation == 'off_grid':
                        tes_avail = max(0, tes_MWh_t)
                    # how much tes MWh_e are available for use
                    tes_avail_e = tes_avail * tes_t2e
            
                    # tes_power_minimum ensures no power cycling for small loads in normal operation
                    if operation == 'normal':
                        tes_power_minimum = tes.power_minimum_MW_e
                    elif operation == 'off_grid':
                        tes_power_minimum = 0  # no minimum in off-grid operation
            
                    tes2load = 0
                    gas2load_e = 0
                    gas2load = 0
                    mass2load = 0
                    gasprice2load = 0
            
                    # Check if unmet_load_MW is greater than or equal to tes_power_minimum
                    if unmet_load_MW >= tes_power_minimum:
                        if self.tes_gasbackup == True:
                            tes2load_e = min([val for val in [unmet_load_MW, unmet_target_load_MW, tes.power_rating_MW_e, poi_remaining] if val is not None])
                            if tes_avail_e >= tes2load_e:
                                tes2load = tes2load_e / tes_t2e
                                gas2load_e = tgl_val
                            else:
                                gas2load_e = (tes2load_e - tes_avail_e) + tgl_val
                                gas2load = gas2load_e / t2e_gas / eta_cc 
                                mass2load = (gas2load * 3.6e6) / LHV_gas 
                                gasprice2load = mass2load * kg2mmbtu * gas_cost[i]
                                tes2load = tes_avail_e / tes_t2e
                        else:
                            if unmet_target_load_MW is None or unmet_target_load_MW >= tes_power_minimum:
                                tes2load = min([val / tes_t2e for val in [tes_avail * tes_t2e, unmet_load_MW, unmet_target_load_MW, tes.power_rating_MW_e, poi_remaining] if val is not None])
                            elif unmet_target_load_MW < tes_power_minimum:
                                total_batt_avail = sum([max([0, min([val for val in [df.loc[i + 1, bes.name + '_MWh_DC'] * bes.discharge_efficiency, bes.power_rating_MW_e] if val is not None])]) for bes in bes_systems])
                                if total_batt_avail >= unmet_target_load_MW:
                                    tes2load = 0
                                else:
                                    tes2load = min([val / tes_t2e for val in [tes_avail * tes_t2e, unmet_load_MW, tes.power_rating_MW_e, poi_remaining] if val is not None])
                        
                    tes_frac_gas = (tes2load * tes_t2e + gas2load_e) / tes.power_rating_MW_e
                    tes_frac_nogas = (tes2load * tes_t2e) / tes.power_rating_MW_e
            
                    tes_MWh_t -= tes2load
                    unmet_load_MW -= (tes2load * tes_t2e) + gas2load_e 

                    if unmet_load_MW <0:
                        unmet_load_MW = 0
            
                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0, unmet_target_load_MW - ((tes2load * tes_t2e) + gas2load_e - tgl_val))                
            
                    poi_remaining -= tes2load * tes_t2e

                    csp_avail = sum([df[csp.name + '_heat_unused_MWh_t'].get(i + 1) for csp in csp_systems if csp.name in tes.systems_charging])
    
                    tes_power_headroom = max(0,min([val for val in [unmet_load_MW, tes.power_rating_MW_e, poi_remaining, csp_avail * tes.charge_efficiency_t2TES * tes_t2e] if val is not None]))
                    if tes_power_headroom > 0:
                        csp_total = tes_power_headroom / (tes.charge_efficiency_t2TES * tes_t2e)
                        for csp in csp_systems:
                            # Ensures each CSP system is checked for charging each TES
                            if csp.name not in tes.systems_charging:
                                continue
                            
                            # Tracking in loop, updated end of loop
                            csp_remaining = df.loc[i + 1, csp.name + '_heat_unused_MWh_t']
                            
                            # Amount of CSP heat transferred, limited by availability, charge rate, and TES headroom
                            csp2tes = max(0, min([val for val in [csp_remaining, csp_total] if val is not None]))  # Check charge rate efficiency
                            
                            # CSP heat left over
                            csp_remaining -= csp2tes
                            csp_total -= csp2tes
                            
                            # CSP heat at this timestep
                            df.loc[i + 1, csp.name + '_to_' + tes.name + '_MWh_t'] += csp2tes
                            tes_cols.append(csp.name + '_to_' + tes.name + '_MWh_t')
                            
                            # Tracking remaining CSP heat after charging TES
                            df.loc[i + 1, csp.name + '_heat_unused_MWh_t'] = csp_remaining
    
                        unmet_load_MW -= tes_power_headroom
                        tes2load += tes_power_headroom/tes_t2e
            
                    # updating tes at this timestamp after load contribution
                    df.loc[i+1, tes.name+'_MWh_t'] = tes_MWh_t
                    # tracking load contribution in thermal
                    df.loc[i+1, tes.name+'_to_load_MWh_t'] = tes2load
                    # tracking load contribution in gas backup
                    df.loc[i+1, tes.name+'_to_load_MWh_gas_e'] = gas2load_e
                    # tracking thermal load contribution in gas backup
                    df.loc[i+1, tes.name+'_to_load_MWh_gas_t'] = gas2load
                    # tracking fuel mass contribution in gas backup 
                    df.loc[i+1, tes.name+'_to_load_MWh_gas_kg'] = mass2load
                    df.loc[i+1, tes.name+'_gas_dollars'] = gasprice2load
                    # tracking operational fraction power block
                    df.loc[i+1, tes.name+'_frac_nogas'] = tes_frac_nogas
                    df.loc[i+1, tes.name+'_frac_gas'] = tes_frac_gas
                    # tracking load contribution in electrical
                    df.loc[i+1, tes.name+'_to_load_MWh_e'] = tes2load * tes_t2e
                    # tracking poi_limit
                    df.loc[i+1, tes.site.name+'_POI_MW'] += tes2load * tes_t2e

            if self.tes_gasbackup == False:
                for bes in bes_systems:
                    # rule for max_total_power
                    if (bes.max_total_power_MW is not None) and operation=='normal':
                        pvs, total = bes.max_total_power_MW
                        if not isinstance(pvs, list):
                            pvs = [pvs]
                        #calculate total power of all counted systems for that timestep
                        p = sum([df.loc[i+1,pv+'_to_load_MWh_e'] for pv in pvs])
                        #maximum bes contribution, ensure nonnegative
                        bes_max = max(0,total-p)
                    else:
                        bes_max = bes.power_rating_MW_e
                    #local variable to track bes charge state, updated with charging above
                    bes_MWh = df.loc[i+1,bes.name+'_MWh_DC']

                    # calculate bes available, limited by discharge depth, ensure nonnegative
                    if operation=='normal':
                        bes_avail = max(0,bes_MWh-bes.capacity_MWh_e*(1.-bes.percent_discharge_depth/100.))
                    elif operation=='off_grid':
                        bes_avail = max(0,bes_MWh) #comment out previous 3 lines to account for usable BES capacity 
                        
                    #calculate bes available
                    # bes_avail = max(0,bes_MWh) # bes change
                    if bes.site.POI_limit is not None:
                        poi_remaining = bes.site.POI_limit - df.loc[i+1,bes.site.name+'_POI_MW']
                    else:
                        poi_remaining = np.inf
                    #calculating bes to load, limited by availability, unmet load, and bes power rating
                    bes2load = max([0,min([val/bes.discharge_efficiency for val in [bes_avail*bes.discharge_efficiency, unmet_load_MW, unmet_target_load_MW, bes_max, poi_remaining] if val is not None])])
                    #updating local variable for bes charge state
                    bes_MWh -= bes2load
                    #updating local variable to track unmet load
                    unmet_load_MW -= bes2load*bes.discharge_efficiency
                    if self.target_load_MW is not None:
                        unmet_target_load_MW = max(0,unmet_target_load_MW - bes2load*bes.discharge_efficiency)
    
                    #bes charge state at this timestep
                    df.loc[i+1,bes.name+'_MWh_DC'] = bes_MWh
                    #tracking bes to load at this timestep
                    df.loc[i+1,bes.name+'_to_load_MWh_e'] = bes2load*bes.discharge_efficiency
                    #tracking poi
                    df.loc[i+1,bes.site.name+'_POI_MW'] += bes2load*bes.discharge_efficiency
                    
            #after pv, tes, and csp, any unmet load satisfied by the grid
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


        #reset datetime index
        # df.to_csv('reduced_load_phase2.csv', index=False)
        # if operation =='normal':
        #     save_load = df['ASGARD_TES_1_to_load_MWh_e']
        #     save_load.to_csv('TES_System_to_load.csv')

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


    def group_sum_metrics(self, metrics, label):
        #summing metrics by system type and full system
        syscols = []
        
        for cat in [self.pv_systems, self.csp_systems, self.bes_systems, self.tes_systems]:
            if len(cat)==0:
                continue
            cols = []
            for sys in cat:
                cols.append(sys.name+'_'+label)
                metrics[sys.name+'_'+label] = getattr(sys,label)

            metrics[sys.__class__.__name__+'_'+label]=sum([metrics[n] for n in cols])

            syscols.append(sys.__class__.__name__+'_'+label)

        metrics['system_'+label] = sum([metrics[n] for n in syscols])

        return metrics

    def storage_power_metrics(self, metrics):
        # metrics['annual_electricity_sales_USD'] = self.timeseries['electricity_sale_in_hour'].values.sum()
        metrics['annual_electricity_sales_USD'] = self.timeseries['electricity_sale_in_hour'].groupby(by=self.timeseries.index.year).sum().astype(int).to_list()
            
        #Add TES system metrics
        add = 0
        for sys in self.tes_systems:
            add = np.array(self.timeseries[sys.name+'_gas_dollars'].groupby(by=self.timeseries.index.year).sum().astype(int).to_list())
            add = add + add
            
            metrics[sys.name + '_charge_rate_resistive_MW_e'] = sys.charge_rate_resistive_MW_e
            metrics[sys.name + '_power_rating_MW_e'] = sys.power_rating_MW_e
            
            tes_frac_col_nogas = sys.name + '_frac_nogas'
            if tes_frac_col_nogas in self.timeseries.columns:
                frac_nogas_array = self.timeseries[tes_frac_col_nogas].values
                metrics[sys.name + '_sum_frac_nogas'] = frac_nogas_array.sum() / 8760 / metrics['years']
                metrics[sys.name + '_frac_nogas_array'] = frac_nogas_array.tolist()
    
            tes_frac_col_gas = sys.name + '_frac_gas'
            if tes_frac_col_gas in self.timeseries.columns:
                frac_gas_array = self.timeseries[tes_frac_col_gas].values
                metrics[sys.name + '_sum_frac_gas'] = frac_gas_array.sum() / 8760 / metrics['years']
                metrics[sys.name + '_frac_gas_array'] = frac_gas_array.tolist()
    
            # Calculate the number of days the _to_load_MWh_gas_kg metric is active for each TES system
            gas_col = sys.name + '_to_load_MWh_gas_kg'
            if gas_col in self.timeseries.columns:
                gas_data = self.timeseries[gas_col].values
                # Reshape the 8760-hour array into a 365-day array with 24 hours each
                gas_data_reshaped = gas_data.reshape((365 * int(metrics['years']), 24))
    
                # Calculate the total number of hours the gas was active each day
                active_hours_per_day = (gas_data_reshaped > 0).sum(axis=1)
                metrics[sys.name + '_active_hours_per_day_gas'] = active_hours_per_day.tolist()
    
                # Calculate the total kg of gas consumed each day
                total_gas_consumed_per_day = gas_data_reshaped.sum(axis=1)
                metrics[sys.name + '_total_gas_consumed_per_day'] = total_gas_consumed_per_day.tolist()
    
                # Check if there is at least one hour in each day where the metric is greater than 0
                active_days = (gas_data_reshaped > 0).any(axis=1).sum()
                metrics[sys.name + '_active_days_gas'] = active_days
        metrics['TES_gas_cost'] = add
    
        # Add BES system metrics
        for sys in self.bes_systems:
            metrics[sys.name + '_power_rating_MW_e'] = sys.power_rating_MW_e
    
        return metrics

    def storage_cost_metrics(self, metrics):
        for sys in self.tes_systems:
            metrics[sys.name+'_Cost_Skip'] = sys.C_skip
            metrics[sys.name+'_Cost_TES_bin'] = sys.C_TES
            metrics[sys.name+'_Cost_HeatExchanger'] = sys.C_hx
            metrics[sys.name+'_Cost_PowerBlock'] = sys.C_pb
            metrics[sys.name+'_Cost_Heater'] = sys.C_heater
        #for sys in self.bes_systems:
            
        return metrics

    def capacity_metrics(self, metrics):
        #summing capacity metrics by system type
        for cat in [self.pv_systems, self.csp_systems, self.bes_systems, self.tes_systems]:
            if len(cat)==0:
                continue
            cols = []
            types = [i for i in cat[0].__dict__ if 'capacity' in i]
            for type in types:
                for sys in cat:
                    cols.append(sys.name+'_'+type)
                    metrics[sys.name+'_'+type] = getattr(sys, type)
                metrics[sys.__class__.__name__+'_'+type] = sum([metrics[n] for n in cols])
        return metrics


    def heliostat_area_metrics(self, metrics):
        # Summing heliostat area metrics by system type
        for cat in [self.csp_systems]:  # Only CSP systems have heliostats
            if len(cat) == 0:
                continue
            cols = []
            for sys in cat:
                # Assuming each CSP system has an attribute 'heliostat_area_m2'
                cols.append(sys.name + '_heliostat_area_m2')
                metrics[sys.name + '_heliostat_area_m2'] = getattr(sys, 'heliostat_area_m2', 0)  # Default to 0 if not present
    
            # Sum the heliostat areas for all CSP systems
            metrics[cat[0].__class__.__name__ + '_heliostat_area_m2'] = sum([metrics[n] for n in cols])
    
        return metrics

    def production_metrics(self, metrics):
        #calculating production metrics for the timeseries
        df = self.timeseries
        #generating list of production columns, assumes contains MWh
        prodcols = [c for c in df.columns if 'MWh' in c]
        #initializing local list to track metrics grouped by generation system but not storage system
        halfcols = []
        for cat in [self.pv_systems, self.csp_systems, self.bes_systems, self.tes_systems]:
            #skip if no systems in category
            if len(cat)==0:
                continue
            #list to track variables for power receipt
            prods = []
            #cycling through systems in the category
            for sys in cat:
                #find all variables that start with that system name
                prods.extend([c.replace(sys.name,'') for c in prodcols if c.startswith(sys.name)])
            #find the list of unique variables
            prods = set(prods)
            #cycle through the unique set
            for prod in prods:
                #tracking the contributing systems for each power receipt variable
                syscols = []   
                for sys in cat:
                    if sys.name+prod in df.columns:
                        syscols.append(sys.name+prod)
                        #cataloging each flow
                        metrics[sys.name+prod]=df[sys.name+prod].sum()
                #cataloging flows from system type to receipt variable
                halfcols.append(sys.__class__.__name__+prod)
                metrics[sys.__class__.__name__+prod] = sum([metrics[n] for n in syscols])

        #grouping receipt variables
        for cat in [self.bes_systems, self.tes_systems]:
            if len(cat)==0:
                continue
            modcols = [h for h in halfcols if any(sys.name in h for sys in cat)]
            for source in [self.pv_systems, self.csp_systems]:
                if len(source)==0:
                    continue
                mets = []
                for sys in cat:
                    mets.extend([m.replace(sys.name,'') for m in modcols if m.startswith(source[0].__class__.__name__+'_to_'+sys.name)])
                for m in mets:
                    syscols = []
                    for sys in cat:
                        syscols.append(source[0].__class__.__name__+'_to_'+sys.name+m.replace(source[0].__class__.__name__+'_to_',''))
                    #cataloging flows from system type to system type
                    metrics[source[0].__class__.__name__+'_to_'+sys.__class__.__name__+m.replace(source[0].__class__.__name__+'_to_','')] = sum([metrics[n] for n in syscols])

        return metrics

    def generation_metrics(self, metrics):
        #summing generation by each system and system type
        df = self.timeseries

        #for pv
        pvcols = []
        for sys in self.pv_systems:
            pvcols.append(sys.name+'_energy_MWh_AC')
            metrics[sys.name+'_energy_MWh_AC'] = df[sys.name+'_power_MW_AC'].sum()
        if len(pvcols)!=0:
            metrics[sys.__class__.__name__+'_energy_MWh_AC'] = sum([metrics[n] for n in pvcols])

        #for csp
        cspcols = []
        for sys in self.csp_systems:
            cspcols.append(sys.name+'_energy_MWh_t')
            metrics[sys.name+'_energy_MWh_t'] = df[sys.name+'_heat_MW_t'].sum()
        if len(cspcols)!=0:
            metrics[sys.__class__.__name__+'_energy_MWh_t'] = sum([metrics[n] for n in cspcols])

        return metrics

    def load_satisfaction_annual(self):
        df = self.timeseries.copy()
        conts = []
        for sys in [self.pv_systems, self.tes_systems, self.bes_systems]:
            if len(sys) == 0:
                continue
            # Collect columns with both '_to_load_MWh_e' and '_to_load_MWh_gas_e' suffixes
            cols = [c.name + '_to_load_MWh_e' for c in sys]
            if sys == self.tes_systems:
                cols += [c.name + '_to_load_MWh_gas_e' for c in sys]
            
            # Sum the columns for the current system
            df[sys[0].__class__.__name__ + '_to_load_MWh_e'] = df[cols].sum(axis=1)
            conts.append(sys[0].__class__.__name__ + '_to_load_MWh_e')
        
        # Sum the contributions from all systems
        df['system_to_load_MWh_e'] = df[conts].sum(axis=1)
        
        # Group by year and sum the annual values
        annual = df['system_to_load_MWh_e'].groupby(by=df.index.year).sum().astype(int).to_list()
        return annual


    def LCOE_metrics(self, metrics):
        def augment_array_np(arr, L):
            arr_with_zero = arr  # Use the original array directly
            l_val = arr_with_zero.size
            if L > l_val:
                shortfall = L - l_val
                repeat_times = (shortfall + l_val - 1) // l_val
                repeated_section = np.tile(arr_with_zero, (repeat_times,))[-shortfall:]
                augmented_array = np.concatenate((arr_with_zero, repeated_section))
                return augmented_array
            else:
                return arr_with_zero[:L]
        
        # Calculate depreciation values and fractions
        def calculate_depreciation(analysis_period, system_capex, inflation, recovery_period, itc):
            adjusted_depreciable_base = system_capex * (1 - itc / 2)
            straight_line_rate = 1 / recovery_period
            double_declining_rate = 2 * straight_line_rate
            depreciation_values = [0]  # Year 0 has no depreciation
            depreciable_fractions = [0]  # Year 0 fraction is 0
            remaining_book_value = adjusted_depreciable_base
        
            for v in range(1, analysis_period):
                if v <= recovery_period:
                    current_depreciation = remaining_book_value * double_declining_rate
                    current_depreciation = min(current_depreciation, remaining_book_value)
                    constant_depreciation = current_depreciation * (1 - inflation)**v
                    depreciation_values.append(constant_depreciation)
                    depreciable_fraction = constant_depreciation / adjusted_depreciable_base
                    depreciable_fractions.append(depreciable_fraction)
                    remaining_book_value -= current_depreciation
                else:
                    depreciation_values.append(0)
                    depreciable_fractions.append(0)
        
            return depreciation_values, depreciable_fractions

        # ===============================================================================================
        # Discount Rate Setup 
        # ===============================================================================================
        ITC = self.ITC  # Investment Tax Credit
        DF = self.DF  # Debt Fraction
        COE = self.COE # Cost of Equity
        I = self.I  # Interest rate
        grant_percentage = self.grant_percentage  # Grant percentage
        system_capex_USD = metrics['system_capex_USD']  # System CAPEX in USD

        # C_freight_e = 0.0139
        # C_freight_b = 0.0060
        # C_BOP = 0.01219
        # C_Civil = 0.01177
        
        # system_capex_USD = system_capex_USD * (1 + C_freight_e + C_freight_b + C_BOP + C_Civil)
        # print(f'Base Construction CAPEX: {system_capex_USD/1e6} $M')
        # C_scaffold = 0.00681
        # system_capex_USD = system_capex_USD * (1 + C_scaffold)
        # print(f'+ Indirect Construction CAPEX: {system_capex_USD/1e6} $M')
        # C_eng = 0.02 
        # C_cm = 0.035 
        # C_owner = 0.1 
        # system_capex_USD = system_capex_USD * (1 + C_eng + C_cm + C_owner)
        # C_conting = 0.1
        # system_capex_USD = system_capex_USD * (1 + C_conting)
        # print(f'Total Installed CAPEX: {system_capex_USD/1e6} $M')
        
        system_annual_OM_USD = metrics['system_annual_OM_USD']  # Annual O&M costs in USD
        
        system_annual_VOM_USD = np.array(metrics['system_to_load_annual_MWh_e']) * 1000 * self.VOM
        
        metrics['system_annual_VOM_USD'] = system_annual_VOM_USD
        analysis_period = self.analysis_period  # Analysis period in years
        WACC_n = self.DF*self.I*(1-tax) + (1-self.DF)*self.COE # use in LCOE calcs for "nominal" LCOE
        WACC_r = ((1+WACC_n)/(1+inflation))-1 # use in LCOE calcs for "real" LCOE
        CRF = WACC_r / (1 - (1 + WACC_r)**(-analysis_period))

        # ===============================================================================================
        # Define Revenue, Cost, and Other Cash Flow Arrays 
        # ===============================================================================================     
        annual_OM = np.array([system_annual_OM_USD * ((1 + esc)**(v + 1)) for v in range(1,analysis_period)])
        annual_OM = np.insert(annual_OM,0,0) # single value regardless of year

        annual_VOM = augment_array_np(np.array(system_annual_VOM_USD), analysis_period - 1)
        annual_VOM = np.array([annual_VOM[i] * ((1 + esc) ** (i + 1)) for i in range(len(annual_VOM))])
        annual_VOM = np.insert(annual_VOM, 0, 0)

        if len(self.tes_systems) == 0:
            annual_fuel = [0]
            annual_fuel = augment_array_np(np.array(annual_fuel), analysis_period - 1)  
        else:
            annual_fuel = np.array(metrics['TES_gas_cost'])

            # Resilience Fuel Modifier
            add = 0
            for tes in self.tes_systems:
                add = np.array(tes.resilience_fuel_annual) + add
            aug_rfuel = add
            annual_fuel = annual_fuel + aug_rfuel
            metrics['annual_fuel_cost_USD'] = annual_fuel
            
            annual_fuel = augment_array_np(np.array(annual_fuel), analysis_period - 1)
            annual_fuel = np.array([annual_fuel[i] * ((1 + esc) ** (i + 1)) for i in range(len(annual_fuel))])
            annual_fuel = np.insert(annual_fuel, 0, 0)
        
        if self.total_project_cost == False: # ONLY LOOKING AT NEW SYSTEM (NOT GRID PURCHASES)
            annual_renewables = np.array(metrics['system_to_load_annual_MWh_e']) * 1000
            annual_renewables = augment_array_np(np.array(annual_renewables),analysis_period - 1)
            annual_renewables = np.insert(annual_renewables,0,0)

            # # AVOIDED COST METHOD 
            # annual_electricity_sales = ((np.array(metrics['annual_grid_energy_cost_base']) + np.array(metrics['annual_demand_charge_cost_base'])) - (np.array(metrics['annual_grid_energy_cost']) + np.array(metrics['annual_demand_charge_cost'])))/np.array(metrics['years']) # Avoided ASGARD Costs

            # # CE Concrete Electricity Sales + Avoided Fuel Cost Method
            # annual_electricity_sales = (metrics['export_energy_MWh_e']*self.e_sale * 1000) + (24340.12-metrics['annual_fuel_cost_USD']) # natural gas
            # annual_electricity_sales = (metrics['export_energy_MWh_e']*self.e_sale * 1000) + (402140-metrics['annual_fuel_cost_USD']) # RFO

            # Standard
            annual_electricity_sales = (np.array(metrics['annual_electricity_sales_USD']))
            
            # esc set to 0 due to fixed PPA
            annual_electricity_sales = augment_array_np(np.array(annual_electricity_sales), analysis_period - 1)
            annual_electricity_sales = np.array([annual_electricity_sales[i] * ((1 + 0) ** (i + 1)) for i in range(len(annual_electricity_sales))])
            annual_electricity_sales = np.insert(annual_electricity_sales, 0, 0)

            # Grid cost set to zero when analyzing only new system (not grid purchases)
            metrics['annual_grid_energy_cost'] = 0
            metrics['annual_demand_charge_cost'] = 0
            annual_electricity_purchases = np.array(metrics['annual_grid_energy_cost']) + np.array(metrics['annual_demand_charge_cost'])
            metrics['annual_electricity_purchases_USD'] = annual_electricity_purchases
            annual_electricity_purchases = np.array([annual_electricity_purchases * ((1 + esc)**(v + 1)) for v in range(1,analysis_period)])
            annual_electricity_purchases = np.insert(annual_electricity_purchases,0,0)

            
        else: # LOOKING AT NEW SYSTEM + GRID PURCHASES AND LOAD SATISFACTION THEREFROM
            annual_renewables = np.array(metrics['system_to_load_annual_MWh_e']) * 1000 + np.array(metrics['grid_to_load_MWh_e']) * 1000
            annual_renewables = augment_array_np(np.array(annual_renewables),analysis_period - 1)
            annual_renewables = np.insert(annual_renewables,0,0)

            # esc set to 0 due to fixed PPA
            annual_electricity_sales = (np.array(metrics['annual_electricity_sales_USD']))/np.array(metrics['years']) # annual average  
            metrics['annual_electricity_sales_USD'] = annual_electricity_sales
            annual_electricity_sales = np.array([annual_electricity_sales * ((1 + 0)**(v + 1)) for v in range(1,analysis_period)])
            annual_electricity_sales = np.insert(annual_electricity_sales,0,0)

            # esc set to 0 due to fixed PPA
            annual_electricity_purchases = (np.array(metrics['annual_grid_energy_cost']) + np.array(metrics['annual_demand_charge_cost']))/np.array(metrics['years'])
            metrics['annual_electricity_purchases_USD'] = annual_electricity_purchases
            annual_electricity_purchases = np.array([annual_electricity_purchases * ((1 + esc)**(v + 1)) for v in range(1,analysis_period)])
            annual_electricity_purchases = np.insert(annual_electricity_purchases,0,0)

        add = np.zeros(analysis_period)
        for bes in self.bes_systems:
            add = add + np.array(augment_array_np(np.array(bes.cpx_batt_aug_annual),analysis_period)[:analysis_period])
        aug_batt = add
        metrics['system_cpx_batt_aug_annual'] = list(aug_batt)
        
        add = np.zeros(analysis_period)
        for tes in self.tes_systems:
            add = add + np.array(augment_array_np(np.array(tes.cpx_htr_aug_annual),analysis_period)[:analysis_period])
        aug_htr = add
        metrics['system_cpx_htr_aug_annual'] = list(aug_htr)

        add = np.zeros(analysis_period)
        for tes in self.tes_systems:
            add = add + np.array(augment_array_np(np.array(tes.cpx_media_aug_annual),analysis_period)[:analysis_period])
        aug_media = add
        metrics['system_cpx_media_aug_annual'] = list(aug_media)
        
        # ================================================================================================
        # Main TEA CALCULATIONS
        # ================================================================================================
        depreciation_values, depreciable_fractions = calculate_depreciation(
        analysis_period, system_capex_USD * (1-grant_percentage), inflation, depreciation_period, ITC
        )

        # Calculate Present Value of Depreciation (PVD)
        PVD = sum([
            depreciable_fractions[n] / (1 + WACC_r)**(n)
            for n in range(0, depreciation_period+1)
        ])
        
        # Calculate After-Tax Deduction Fixed Charge Rate (FCR)
        FCR_after_tax_deduction = (
            CRF * (1 - tax * PVD * (1 - ITC / 2) - ITC) +
            insurance * (1 - tax) +
            property_tax * (1 - tax)
        )
        
        # Calculate Before-Tax Revenue Required Fixed Charge Rate (FCR)
        FCR_before_tax_revenue_required = (
            CRF * (1 - tax * PVD * (1 - ITC / 2) - ITC) +
            insurance + property_tax
        ) / (1 - tax)
        
        NPV_OM_N = npf.npv(WACC_r,annual_OM[:analysis_period])
        NPV_VOM_N = npf.npv(WACC_r,annual_VOM[:analysis_period])
        NPV_Energy_N = npf.npv(WACC_r, annual_renewables[:analysis_period])
        NPV_depreciation = npf.npv(WACC_r, depreciation_values[:analysis_period])
        NPV_electricity_sales_N = npf.npv(WACC_r, annual_electricity_sales[:analysis_period])
        NPV_electricity_purchases_N = npf.npv(WACC_r, annual_electricity_purchases[:analysis_period])
        NPV_fuel_purchases_N = npf.npv(WACC_r, annual_fuel[:analysis_period])
        NPV_aug_batt_N = npf.npv(WACC_r, aug_batt[:analysis_period])
        NPV_aug_htr_N = npf.npv(WACC_r, aug_htr[:analysis_period])
        NPV_aug_media_N = npf.npv(WACC_r, aug_media[:analysis_period])
        
        # Annualized costs
        annualized_CAPEX_AT = (1 - grant_percentage) * system_capex_USD * FCR_after_tax_deduction #* (1 - ITC)
        annualized_CAPEX_BT = (1 - grant_percentage) * system_capex_USD * FCR_before_tax_revenue_required #* (1 - ITC)
        annualized_OM_BT = NPV_OM_N * CRF
        annualized_OM_AT = NPV_OM_N * CRF * (1-tax)
        annualized_VOM_BT = NPV_VOM_N * CRF
        annualized_VOM_AT = NPV_VOM_N * CRF * (1-tax)
        annualized_fuel_BT = NPV_fuel_purchases_N * CRF
        annualized_fuel_AT = NPV_fuel_purchases_N * CRF * (1-tax)
        annualized_electricity_purchases_BT = NPV_electricity_purchases_N * CRF
        annualized_electricity_purchases_AT = NPV_electricity_purchases_N * CRF * (1-tax)
        annualized_electricity_sales_BT = NPV_electricity_sales_N * CRF
        annualized_electricity_sales_AT = NPV_electricity_sales_N * CRF * (1-tax)
        annualized_aug_htr_BT = NPV_aug_htr_N * CRF
        annualized_aug_htr_AT = NPV_aug_htr_N * CRF * (1-tax)
        annualized_aug_media_BT = NPV_aug_media_N * CRF
        annualized_aug_media_AT = NPV_aug_media_N * CRF * (1-tax)
        annualized_aug_batt_BT = NPV_aug_batt_N * CRF
        annualized_aug_batt_AT = NPV_aug_batt_N * CRF * (1-tax)
        
        annual_ARR_AT = (annualized_CAPEX_AT + annualized_OM_AT + annualized_VOM_AT + annualized_fuel_AT +
                         annualized_electricity_purchases_AT + annualized_aug_batt_AT + annualized_aug_htr_AT + annualized_aug_media_AT)
        
        annual_ARR_BT = (annualized_CAPEX_BT + annualized_OM_BT + annualized_VOM_BT + annualized_fuel_BT +
                         annualized_electricity_purchases_BT + annualized_aug_batt_BT + annualized_aug_htr_BT + annualized_aug_media_BT)
        
        # Track revenues, costs, and taxes
        revenues = [0]
        costs = [0]
        other_tax = [0]
        taxable_income_array = [0]
        taxes_array = [0]
        annual_cash_flow = [-(system_capex_USD * (1 - ITC) * (1 - grant_percentage))]  # Initial equity investment
        unused_depreciation = 0  # Initialize unused depreciation rollover

        # C&E Analysis (Fuel savings considered)
        # annual_fuel = np.zeros_like(annual_fuel)
        
        for v in range(1, analysis_period):
            OM_esc = annual_OM[v] + annual_VOM[v]
            ebit = (annual_electricity_sales[v]) - (
                OM_esc + annual_fuel[v] + annual_electricity_purchases[v] + aug_batt[v] + aug_htr[v] + aug_media[v]
            )
            depreciation = depreciation_values[v] + unused_depreciation  # Add unused depreciation from previous iteration
            taxable_income = max(0, ebit - depreciation)
            
            # Calculate unused depreciation for rollover
            if ebit - depreciation < 0:
                unused_depreciation = abs(ebit - depreciation)  # Rollover the excess depreciation
            else:
                unused_depreciation = 0  # Reset unused depreciation if none is left
            
            taxes = taxable_income * tax
            net_income = ebit - taxes - (insurance * system_capex_USD * (1 - grant_percentage) + property_tax * system_capex_USD * (1 - grant_percentage))
            
            revenues.append(annual_electricity_sales[v])
            costs.append(OM_esc + annual_fuel[v] + annual_electricity_purchases[v] + aug_batt[v] + aug_htr[v] + aug_media[v])
            other_tax.append(insurance * system_capex_USD * (1 - grant_percentage) + property_tax * system_capex_USD * (1 - grant_percentage))
            taxes_array.append(taxes)
            taxable_income_array.append(taxable_income)
            annual_cash_flow.append(net_income)

        # Calculate IRR and TLCC
        NPV_costs = npf.npv(WACC_r, costs)
        NPV_other_tax = npf.npv(WACC_r, other_tax)
        NPV_cash_flow = npf.npv(WACC_r, annual_cash_flow)

        #print(f'annual cash flow: {annual_cash_flow}')
        IRR = npf.irr(annual_cash_flow)
        print(f'IRR: {IRR*100} %')
        
        after_tax_TLCC = -1 * annual_cash_flow[0] - (tax * NPV_depreciation) + ((1 - tax) * NPV_costs) + ((1-tax) * NPV_other_tax)
        before_tax_TLCC = (-1 * annual_cash_flow[0] - (tax * NPV_depreciation) + ((1 - tax) * NPV_costs)) / (1-tax) + (NPV_other_tax) / (1-tax)
        
        # Solve for after & before tax LCOE
        LCOE_after_tax = after_tax_TLCC / NPV_Energy_N
        LCOE_before_tax = before_tax_TLCC / NPV_Energy_N

        # LCOE calculation
        ARR_AT_array = [0]+[annual_ARR_AT] * (analysis_period)
        ARR_BT_array = [0]+[annual_ARR_BT] * (analysis_period)
        
        # Calculate NPV for ARR_AT and ARR_BT
        NPV_ARR_AT = npf.npv(WACC_r, ARR_AT_array)
        LCOE_real_USD_kWh_AT = NPV_ARR_AT / NPV_Energy_N
        
        NPV_ARR_BT = npf.npv(WACC_r, ARR_BT_array)
        LCOE_real_USD_kWh_BT = NPV_ARR_BT / NPV_Energy_N

        print(f'LCOE BT: {LCOE_real_USD_kWh_BT} $/kWh')

        # Initial investment (negative cash flow in year 0)
        initial_investment = -annual_cash_flow[0]
        
        # Calculate cumulative cash flow
        cumulative_cash_flow = [0]  # Start with year 0
        for cash_flow in annual_cash_flow[1:]:  # Skip the initial investment
            cumulative_cash_flow.append(cumulative_cash_flow[-1] + cash_flow)
        
        # Calculate payback period
        payback_period = None
        for year, cash in enumerate(cumulative_cash_flow):
            if cash >= initial_investment:
                payback_period = year
                break

        print(f'Payback Period: {payback_period} Years')

        metrics['PVD'] = PVD
        metrics['FCR_AT'] = FCR_after_tax_deduction
        metrics['FCR_BT'] = FCR_before_tax_revenue_required
        metrics['CRF'] = CRF
        metrics['NPV_cash_flow'] = NPV_cash_flow
        metrics['IRR'] = IRR
        metrics['payback_period'] = payback_period
        metrics['LCOE_real_USD_kWh'] = LCOE_real_USD_kWh_BT
        metrics['LCOE_real_USD_kWh_AT'] = LCOE_real_USD_kWh_AT
        
        return metrics
    
    def system_metrics(self):
        #master function to generate system metrics
        df = self.timeseries.copy()
        df.index = pd.to_datetime(df.index)
        
        metrics = {}
        
        #list systems of each type
        metrics['PV_systems'] = [pv.name for pv in self.pv_systems]
        metrics['CSP_systems'] = [csp.name for csp in self.csp_systems]
        metrics['BES_systems'] = [bes.name for bes in self.bes_systems]
        metrics['TES_systems'] = [tes.name for tes in self.tes_systems]

        #list systems that work off-grid
        metrics['off_grid_systems'] = [sys.name for sys in list(chain.from_iterable([self.pv_systems_off_grid, self.csp_systems_off_grid,self.bes_systems_off_grid, self.tes_systems_off_grid]))]

        #calculate number of years in timeseries
        metrics['years'] = len(df)/(24*365)

        metrics['load_MWh'] = df.load_MW.sum()
        metrics['load_annual_MWh'] = df.load_MW.groupby(df.index.year).sum().astype(int).to_list()

        metrics = self.capacity_metrics(metrics)
        metrics = self.storage_power_metrics(metrics)
        metrics = self.heliostat_area_metrics(metrics)
        
        for label in ['area_land_acres','capex_USD','annual_OM_USD']:
            metrics = self.group_sum_metrics(metrics, label)

        metrics = self.storage_cost_metrics(metrics)
            
        metrics = self.generation_metrics(metrics)
        
        metrics = self.production_metrics(metrics)


        metrics['grid_to_load_MWh_e'] = df.grid_to_load_MWh_e.sum()
        metrics['grid_to_load_annual_MWh_e'] = df.grid_to_load_MWh_e.groupby(df.index.year).sum().astype(int).to_list()
        metrics['system_to_load_annual_MWh_e'] = self.load_satisfaction_annual()
        
        # Define the number of hours in each month for a non-leap year
        hours_in_month = {
            'January': 744,
            'February': 672,
            'March': 744,
            'April': 720,
            'May': 744,
            'June': 720,
            'July': 744,
            'August': 744,
            'September': 720,
            'October': 744,
            'November': 720,
            'December': 744
        }
        
        # Define the TOU rates (Utilitly Plant)
        customer_charge = 446.70
        on_peak_demand_charge_summer = 20 * 1000  # in $/kW
        on_peak_demand_charge_non_summer = 20 * 1000  # in $/kW
        on_peak_energy_charge_summer = 0.08 * 1000 # in $/kWh
        on_peak_energy_charge_non_summer = 0.08 * 1000 # in $/kWh
        off_peak_energy_charge_summer = 0.08 * 1000
        off_peak_energy_charge_non_summer = 0.08 * 1000
        
        # Define the months considered as summer
        summer_months = ['June', 'July', 'August'] 
        
        # Extract the grid-to-load data as a NumPy array
        df_grid_to_load_MWh_e = df['grid_to_load_MWh_e'].to_numpy()
        df_base_load = np.array(df.load_MW)       
        # Check the size of the data
        data_size = len(df_grid_to_load_MWh_e)       
        # Create a mask for on-peak hours (Monday to Friday, 8 AM to 8 PM)
        on_peak_mask = np.zeros(data_size, dtype=bool)       
        # Create a mask for each hour of the year
        for hour in range(data_size):
            # Get the day of the week and hour of the day
            day_of_year = hour // 24
            hour_of_day = hour % 24
            day_of_week = (day_of_year % 7)  # 0 = Sunday, 1 = Monday, ..., 6 = Saturday  
            # Set on-peak hours for Monday to Friday (1 to 5)
            if day_of_week < 5 and 8 <= hour_of_day < 20:  # 8 AM to 8 PM
                on_peak_mask[hour] = True    
        # Initialize dictionaries to hold results
        monthly_on_peak_peaks = {}
        monthly_energy_costs = {}
        monthly_on_peak_peaks_b = {}
        monthly_energy_costs_b = {}
        start_hour = 0       
        # Loop through each month and calculate the peak demand and energy costs
        for month, hours in hours_in_month.items():
            end_hour = start_hour + hours
            if end_hour > data_size:
                print(f"Warning: End hour {end_hour} exceeds the size of the data array. Adjusting to {data_size}.")
                end_hour = data_size  # Adjust to the size of the data array        
            # Filter the on-peak hours for the current month using the mask
            month_on_peak_demand = df_grid_to_load_MWh_e[start_hour:end_hour][on_peak_mask[start_hour:end_hour]]
            monthly_on_peak_peaks[month] = np.max(month_on_peak_demand) if month_on_peak_demand.size > 0 else 0
            month_on_peak_demand_b = df_base_load[start_hour:end_hour][on_peak_mask[start_hour:end_hour]]
            monthly_on_peak_peaks_b[month] = np.max(month_on_peak_demand_b) if month_on_peak_demand_b.size > 0 else 0 
            # Calculate total energy consumed during on-peak and off-peak hours
            month_on_peak_energy = df_grid_to_load_MWh_e[start_hour:end_hour][on_peak_mask[start_hour:end_hour]]
            month_off_peak_energy = df_grid_to_load_MWh_e[start_hour:end_hour][~on_peak_mask[start_hour:end_hour]]
            month_on_peak_energy_b = df_base_load[start_hour:end_hour][on_peak_mask[start_hour:end_hour]]
            month_off_peak_energy_b = df_base_load[start_hour:end_hour][~on_peak_mask[start_hour:end_hour]]
            # Calculate energy costs
            if month in summer_months:
                on_peak_energy_cost = np.sum(month_on_peak_energy) * on_peak_energy_charge_summer
                off_peak_energy_cost = np.sum(month_off_peak_energy) * off_peak_energy_charge_summer  # Assuming off-peak is charged the same in summer
                on_peak_energy_cost_b = np.sum(month_on_peak_energy_b) * on_peak_energy_charge_summer
                off_peak_energy_cost_b = np.sum(month_off_peak_energy_b) * off_peak_energy_charge_summer  # Assuming off-peak is charged the same in summer
            else:
                on_peak_energy_cost = np.sum(month_on_peak_energy) * on_peak_energy_charge_non_summer
                off_peak_energy_cost = np.sum(month_off_peak_energy) * off_peak_energy_charge_non_summer  # Assuming off-peak is charged the same in non-summer
                on_peak_energy_cost_b = np.sum(month_on_peak_energy_b) * on_peak_energy_charge_non_summer
                off_peak_energy_cost_b = np.sum(month_off_peak_energy_b) * off_peak_energy_charge_non_summer  # Assuming off-peak is charged the same in non-summer
            # Total energy cost for the month
            total_energy_cost = on_peak_energy_cost + off_peak_energy_cost + customer_charge
            monthly_energy_costs[month] = total_energy_cost
            total_energy_cost_b = on_peak_energy_cost_b + off_peak_energy_cost_b + customer_charge
            monthly_energy_costs_b[month] = total_energy_cost_b
            # Print the results for the month
            if monthly_on_peak_peaks[month] > 0:
                if month in summer_months:
                    demand_charge = monthly_on_peak_peaks[month] * on_peak_demand_charge_summer
                    demand_charge_b = monthly_on_peak_peaks_b[month] * on_peak_demand_charge_summer
                else:
                    demand_charge = monthly_on_peak_peaks[month] * on_peak_demand_charge_non_summer
                    demand_charge_b = monthly_on_peak_peaks_b[month] * on_peak_demand_charge_non_summer
                billing_charge = customer_charge + demand_charge
                billing_charge_b = customer_charge + demand_charge_b
            start_hour = end_hour
        
        # Calculate the total annual demand charge cost
        annual_demand_charge_cost = sum(
            (monthly_on_peak_peaks[month] * (on_peak_demand_charge_summer if month in summer_months else on_peak_demand_charge_non_summer) + customer_charge)
            for month in hours_in_month
        )
        metrics['annual_demand_charge_cost'] = annual_demand_charge_cost

        annual_demand_charge_cost_b = sum(
            (monthly_on_peak_peaks_b[month] * (on_peak_demand_charge_summer if month in summer_months else on_peak_demand_charge_non_summer) + customer_charge)
            for month in hours_in_month
        )
        metrics['annual_demand_charge_cost_base'] = annual_demand_charge_cost_b
        
        # Calculate the total annual grid energy cost
        annual_grid_energy_cost = sum(monthly_energy_costs.values())
        metrics['annual_grid_energy_cost'] = annual_grid_energy_cost

        annual_grid_energy_cost_b = sum(monthly_energy_costs_b.values())
        metrics['annual_grid_energy_cost_base'] = annual_grid_energy_cost_b
            
        metrics['percent_load_by_grid'] = 100*metrics['grid_to_load_MWh_e']/metrics['load_MWh']
        if len(self.tes_systems) != 0:
            metrics['percent_load_by_gas'] = 100*metrics['TES_System_to_load_MWh_gas_e']/metrics['load_MWh']
            metrics['renewable_percent_load_by_system_realtime'] = 100*(metrics['system_to_load_annual_MWh_e'] - metrics['TES_System_to_load_MWh_gas_e'])/metrics['load_MWh']
        
        metrics['percent_load_by_system_realtime'] = 100-metrics['percent_load_by_grid']

        if self.target_load_MW is not None: # gas load not separated explicitly 
            metrics['percent_time_meets_target_load'] = 100*(df.unmet_target_load_MWh_e==0).sum()/len(df)
            metrics['percent_target_load_met'] = 100*(1-df.unmet_target_load_MWh_e.sum()/df.target_load_MW.sum())
            if len(self.tes_systems) != 0:
                metrics['renewable_percent_target_load_met'] = 100*(((df.target_load_MW.sum() - df.unmet_target_load_MWh_e.sum()) - (metrics['TES_System_to_load_MWh_gas_e'] - (df.target_load_MW.sum()/self.load_factor)*(1-self.load_factor)))/(df.target_load_MW.sum()/self.load_factor))
            else:
                metrics['renewable_percent_target_load_met'] = metrics['percent_target_load_met']
            metrics['unmet_target_load_MWh_e'] = df.unmet_target_load_MWh_e.sum()
            metrics['target_load_MWh_e'] = df.target_load_MW.sum()
            metrics['export_energy_MWh_e'] = df.export_energy_MWh_e.sum()
            metrics['min_system_power_to_target_load_MW'] = (df[df.target_load_MW!=0].target_load_MW- df[df.target_load_MW!=0].unmet_target_load_MWh_e).min()
        
        # List TEA Metrics
        metrics = self.LCOE_metrics(metrics)
        
        return metrics

    def randomstart(self, critical_load_mw, target_hours):

        start = randint(1, len(self.timeseries)) #start anywhere
    
        df_res = pd.concat([self.timeseries.copy().iloc[start::,:],self.timeseries.copy().iloc[::start,:]]) #loop through the full timeseries
    
        res_results = {}

        lasthour_actual, to_end_actual, pct_target_energy_actual, target_energy_actual = self.operation(operation='off_grid', critical_load_MW = critical_load_mw, target_hours=target_hours, df_res = df_res, res_initial = 'actual')
    
        lasthour_full, to_end_full, pct_target_energy_full, target_energy_full = self.operation(operation='off_grid', critical_load_MW = critical_load_mw, target_hours=target_hours, df_res = df_res, res_initial = 'full')
    
        res_results['start_hour']=start
        res_results['actual_duration_hours']=lasthour_actual
        res_results['full_duration_hours']=lasthour_full
        res_results['to_end_actual']=to_end_actual
        res_results['to_end_full']=to_end_full
        res_results['pct_target_energy_actual']=pct_target_energy_actual
        res_results['pct_target_energy_full']=pct_target_energy_full
        res_results['target_energy_actual']=target_energy_actual
        res_results['target_energy_full']=target_energy_full
            
        return res_results

    def resilience_cases(self, critical_load_MW, target_hours, n_starts = 10):
        
        #random sampling and resiliency analysis
        df_summary = pd.DataFrame(columns=['start_hour','actual_duration_hours','full_duration_hours','to_end_actual','to_end_full','pct_target_energy_actual','pct_target_energy_full','target_energy_actual','target_energy_full'])
    
        async_results = []
        with mp.Pool(processes=mp.cpu_count()) as pool:
            for _ in range(n_starts):
                async_results.append(pool.apply_async(self.randomstart, args=[critical_load_MW, target_hours]))
            pool.close()
            pool.join()
        
        for num, async_result in enumerate(async_results):
            df_summary=pd.concat([df_summary, pd.DataFrame(async_result.get(),index=[int(num),])])
        
        return df_summary

    def resilience_metrics(self, df ,target_hours):
        results = {}
        results['pct_meets_actual'] = (df['actual_duration_hours']>=target_hours).sum()/len(df)
        results['pct_meets_full']=(df['full_duration_hours']>=target_hours).sum()/len(df)
        
        results['tenth_pctile_actual_hrs'] = df['actual_duration_hours'].quantile(.1)
        results['fiftieth_pctile_actual_hrs'] = df['actual_duration_hours'].quantile(.5)
        results['ninetieth_pctile_actual_hrs'] = df['actual_duration_hours'].quantile(.9)
        results['tenth_pctile_full_hrs'] = df['full_duration_hours'].quantile(.1)
        results['fiftieth_pctile_full_hrs'] = df['full_duration_hours'].quantile(.5)
        results['ninetieth_pctile_full_hrs'] = df['full_duration_hours'].quantile(.9)
        
        results['actual_reaches_end_pct'] = df['to_end_actual'].sum()/len(df)
        results['full_reaches_end_pct'] = df['to_end_full'].sum()/len(df)
        
        results['tenth_pctile_pct_target_energy_actual'] = df['pct_target_energy_actual'].quantile(.1)*100
        results['fiftieth_pctile_pct_target_energy_actual'] = df['pct_target_energy_actual'].quantile(.5)*100
        results['tenth_pctile_pct_target_energy_full'] = df['pct_target_energy_full'].quantile(.1)*100
        results['fiftieth_pctile_pct_target_energy_full'] = df['pct_target_energy_full'].quantile(.5)*100

        results['tenth_pctile_target_energy_actual'] = df['target_energy_actual'].quantile(.1)
        results['fiftieth_pctile_target_energy_actual'] = df['target_energy_actual'].quantile(.5)
        results['ninetieth_pctile_target_energy_actual'] = df['target_energy_actual'].quantile(.9)
        results['tenth_pctile_target_energy_full'] = df['target_energy_full'].quantile(.1)
        results['fiftieth_pctile_target_energy_full'] = df['target_energy_full'].quantile(.5)
        results['ninetieth_pctile_target_energy_full'] = df['target_energy_full'].quantile(.9)

        results['pct_meets_target_energy_actual'] = 100*(df['pct_target_energy_actual']==1.).sum()/len(df)
        results['pct_meets_target_energy_full'] = 100*(df['pct_target_energy_full']==1.).sum()/len(df)

        def calculate_propane(X, tanker_capacity_gallons=5000):
            # Constants
            MWh_to_Btu = 3.412*1e6
            efficiency = 0.386*0.9
            btu_per_gallon_propane = 91500  # BTU per gallon of propane
            gallons_to_cubic_feet = 0.133681
            co2_per_gallon_propane = 5.74  # kg CO2 per gallon of propane
        
            # Step 1: Convert MWh to MMBtu
            electrical_energy_mmbtu = X * MWh_to_Btu
        
            # Step 2: Calculate Total Thermal Energy Required
            total_thermal_energy_mmbtu = electrical_energy_mmbtu / efficiency
        
            # Step 3: Calculate Propane Required in gallons
            propane_required_gallons = total_thermal_energy_mmbtu / btu_per_gallon_propane
        
            # Step 4: Estimate Number of Tanker Trucks
            tanker_capacity_gallons = tanker_capacity_gallons  # Already in gallons
            number_of_trucks = propane_required_gallons / tanker_capacity_gallons
        
            # Step 5: Calculate CO2 emissions
            total_co2_emissions_kg = propane_required_gallons * co2_per_gallon_propane
            total_co2_emissions_metric_tons = total_co2_emissions_kg / 1000  # Convert kg to metric tons
        
            return {
                'Total Thermal Energy (MMBtu)': total_thermal_energy_mmbtu,
                'Propane Required (gallons)': propane_required_gallons,
                'Number of Tanker Trucks': number_of_trucks,
                'Total CO2 Emissions (metric tons)': total_co2_emissions_metric_tons
            }
        
        for key in ['tenth_pctile_target_energy_actual', 'fiftieth_pctile_target_energy_actual','ninetieth_pctile_target_energy_actual']:
            X = results[key]
            data = calculate_propane(X)
            
            # Add results to metrics
            results[f'{key}_propane_gallons'] = data['Propane Required (gallons)']
            results[f'{key}_co2_emissions_metric_tons'] = data['Total CO2 Emissions (metric tons)']
        
        return results

    # STANDARD PLOTTING
    def timeseries_plot_source(self, start_date='random', days=365, type='area', color_seq=None, system_seq=None):
        # Plotting contributions to load by individual systems
        df = self.timeseries.copy()
    
        # Starting at random midnight
        ndays = len(df) / 24
        if start_date == 'random':
            start_date = df.index[randrange(int(ndays - days)) * 24]
        else:
            start_date = pd.to_datetime(start_date)
        end_date = start_date + DT.timedelta(days=days)
    
        df2 = df.loc[start_date:end_date].copy()
    
        if system_seq is None:
            conts = []
            
            for sys in [self.pv_systems, self.tes_systems, self.bes_systems]:
                if len(sys) == 0:
                    continue
                # Collect columns with '_to_load_MWh_e' suffix
                cols = [c.name + '_to_load_MWh_e' for c in sys]
                # If the system is tes_systems, also collect columns with '_to_load_MWh_gas_e' suffix
                if sys == self.tes_systems:
                    gas_cols = [c.name + '_to_load_MWh_gas_e' for c in sys]
                    df2[sys[0].__class__.__name__ + '_to_load_MWh_gas_e'] = df2[gas_cols].sum(axis=1)
                    conts.append(sys[0].__class__.__name__ + '_to_load_MWh_gas_e')
                
                # Sum the columns for the current system
                df2[sys[0].__class__.__name__ + '_to_load_MWh_e'] = df2[cols].sum(axis=1)
                conts.append(sys[0].__class__.__name__ + '_to_load_MWh_e')
    
            # Add grid_to_load_MWh_e to the contributions
            if 'grid_to_load_MWh_e' in df2.columns:
                conts.append('grid_to_load_MWh_e')
        
        else:
            conts = system_seq
    
        fig, ax = plt.subplots()
        # ax.plot(df2[['load_MW']], linestyle='-', color='black')
    
        if type == 'bar':
            df2[conts].plot(kind='bar', stacked=True, width=1, ax=ax, alpha=1)
        elif type == 'area':
            if color_seq is None:
                df2[conts].plot.area(stacked=True, ax=ax, lw=0, alpha=1)
            else:
                df2[conts].plot.area(stacked=True, ax=ax, lw=0, color=color_seq, alpha=1)
    
        #df2[['load_MW']].plot(linestyle='-', color='black', ax=ax, label=None)
        if self.target_load_MW is not None:
            df2[['target_load_MW']].plot(linestyle='--', color='black', ax=ax, label='PV+TES Target Load')
            (df2[['target_load_MW']]/0.25).plot(linestyle='-', color='black', ax=ax, label='Actual Load')
    
        plt.ylabel('Hourly Energy (MWh)')
        # plt.ylim([0,80])
        plt.legend(loc='upper left', bbox_to_anchor=(1.02, 1))
        output_dir = 'output_data'
        plt.savefig(os.path.join(output_dir, f"load_satisfaction.png"), bbox_inches='tight')

    # Luke CUSTOM
    # def timeseries_plot_source(self, start_date='random', days=365, type='area', color_seq=None, system_seq=None):
    #     # Plotting contributions to load by individual systems
    #     df = self.timeseries.copy()
    
    #     # Starting at random midnight
    #     ndays = len(df) / 24
    #     if start_date == 'random':
    #         start_date = df.index[randrange(int(ndays - days)) * 24]
    #     else:
    #         start_date = pd.to_datetime(start_date)
    #     end_date = start_date + DT.timedelta(days=days)
    
    #     df2 = df.loc[start_date:end_date].copy()
    
    #     if system_seq is None:
    #         conts_target = []
    #         conts_full = []
    #         conts_export = []
            
    #         for sys in [self.pv_systems, self.tes_systems, self.bes_systems]:
    #             if len(sys) == 0:
    #                 continue

    #             # If the system is tes_systems, also collect columns with '_to_load_MWh_gas_e' suffix
    #             if sys == self.tes_systems:
    #                 tes_cols = [c.name + '_to_load_MWh_e' for c in self.tes_systems]
    #                 df2['TES to Target Load'] = df2[tes_cols].sum(axis=1)
    #                 conts_target.append ('TES to Target Load')

                
    #             if sys == self.tes_systems:
    #                 gas_cols = [c.name + '_to_load_MWh_gas_e' for c in self.tes_systems]
    #                 df2['Gas to Load'] = df2[gas_cols].sum(axis=1)
    #                 conts_target.append('Gas to Load')

    #             # Calculate total PV output and excess PV
    #             if sys == self.pv_systems:
    #                 pv_cols = [c.name + '_to_load_MWh_e' for c in self.pv_systems]
    #                 df2['total_pv_output'] = df2[pv_cols].sum(axis=1)
    #                 df2['PV to Target Load'] = np.where(df2['total_pv_output'] >= df2['target_load_MW'],
    #                                               df2['target_load_MW'],
    #                                               df2['total_pv_output'])
    #                 conts_target.append('PV to Target Load')

    #             # Calculate total PV output and excess PV
    #             if sys == self.pv_systems:
    #                 pv_cols = [c.name + '_to_load_MWh_e' for c in self.pv_systems]
    #                 df2['total_pv_output'] = df2[pv_cols].sum(axis=1)
        
    #                 # Use np.where to set values based on the condition
    #                 df2['PV Export'] = np.where(df2['total_pv_output'] >= df2['target_load_MW'],
    #                                             df2['total_pv_output'] - df2['target_load_MW'],
    #                                             0)
    #                 conts_export.append('PV Export')
                
    
    #         # # Add grid_to_load_MWh_e to the contributions
    #         # if 'grid_to_load_MWh_e' in df2.columns:
    #         #     conts.append('grid_to_load_MWh_e')

    #     else:
    #         conts = system_seq
        
    #     fig, ax = plt.subplots()

    #     # Plot the contributions for target load
    #     if type == 'bar':
    #         # Plot conts_target stacked from zero
    #         df2[conts_target].plot(kind='bar', stacked=True, width=1, ax=ax, alpha=1, legend=False)
        
    #         # Plot conts_full stacked from target_load_MW
    #         bottom_full = df2['target_load_MW']
    #         df2[conts_full].plot(kind='bar', stacked=True, width=1, ax=ax, alpha=1, bottom=bottom_full, legend=False)
        
    #         # Plot conts_export stacked from target_load_MW
    #         bottom_export = df2['target_load_MW']
    #         df2[conts_export].plot(kind='bar', stacked=True, width=1, ax=ax, alpha=1, bottom=bottom_export, legend=False)
        
    #     elif type == 'area':
    #         # Plot conts_target stacked from zero
    #         df2[conts_target].plot.area(stacked=True, ax=ax, lw=0, alpha=1, legend=False)
        
    #         # Calculate the cumulative sum for conts_full and conts_export
    #         full_sum = df2[conts_full].sum(axis=1)
    #         export_sum = df2[conts_export].sum(axis=1)
        
    #         # Fill between for conts_full starting from target_load_MW
    #         # ax.fill_between(df2.index, 0, 0+ full_sum, 
    #         #                 color='tab:red', alpha=1, label='Remaining Gas to Load')
        
    #         # Fill between for conts_export starting from target_load_MW
    #         ax.fill_between(df2.index, df2['target_load_MW'], df2['target_load_MW'] + export_sum, 
    #                         color='tab:purple', alpha=1, label='PV Export Beyond Target Load')
        
    #     # Add target load lines with custom labels
    #     if self.target_load_MW is not None:
    #         df2['PV+TES Target Load'] = df2['target_load_MW']
    #         df2['Actual Heat Load'] = df2['target_load_MW']/0.25
    #         df2[['PV+TES Target Load']].plot(linestyle='--', color='black', ax=ax, label='PV+TES Target Load')
    #         df2[['Actual Heat Load']].plot(linestyle='-', color='black', ax=ax, label='Actual Load')
        
    #     plt.ylabel('Hourly Energy (MWh)')
    #     plt.legend(loc='upper left', bbox_to_anchor=(1.02, 1))
    #     plt.ylim([0,0.6])
    #     output_dir = 'output_data'
    #     plt.savefig(os.path.join(output_dir, f"load_satisfaction_noexport_gas_LF=25.png"), bbox_inches='tight')


    def timeseries_plot_group(self,start_date='random',days=7):
        #plotting contributions to load by system group (pv, tes, bes)
    
        df=self.timeseries.copy()
        
        ndays = len(df)/24
        if start_date == 'random':
            start_date = df.index[randrange(ndays-days)*24]
        else:
            start_date = pd.to_datetime(start_date)
        end_date = start_date + DT.timedelta(days=days)

        df2 = df.loc[start_date:end_date].copy()
        conts = []
        for sys in [self.pv_systems, self.tes_systems, self.bes_systems]:
            if len(sys)==0:
                continue
            cols = [c.name+'_to_load_MWh_e' for c in sys]
            df2[sys[0].__class__.__name__+'_to_load_MWh_e'] = df2[cols].sum(axis=1)
            conts.append(sys[0].__class__.__name__+'_to_load_MWh_e')
        
        #df.load_MW.plot()
        df2.plot.area(y=conts, stacked=True,use_index=True,lw=0)
        plt.plot(df2['load_MW'],color='black')
        plt.xlim(start_date,end_date)
        plt.ylabel('Hourly Energy (MWh)')
        plt.show()


    def plot_tes_capacity(self, start_date='random', days=365, type='area', color_seq=None, system_seq=None):
        # Plotting TES capacity over time
    
        df = self.timeseries.copy()
    
        # Starting at random midnight
        ndays = len(df) / 24
        if start_date == 'random':
            start_date = df.index[randrange(int(ndays - days)) * 24]
        else:
            start_date = pd.to_datetime(start_date)
        end_date = start_date + pd.Timedelta(days=days)
    
        df2 = df.loc[start_date:end_date].copy()
    
        if system_seq is None:
            conts = [tes.name + '_MWh_t' for tes in self.tes_systems]
        else:
            conts = system_seq
    
        fig, ax = plt.subplots()
        if type == 'bar':
            df2[conts].plot(kind='bar', stacked=True, width=1, ax=ax)
    
        elif type == 'area':
            if color_seq is None:
                df2[conts].plot.area(stacked=False, ax=ax, lw=0)
            else:
                df2[conts].plot.area(stacked=True, ax=ax, lw=0, color=color_seq)
    
        plt.ylabel('Stored Energy (MWh_thermal)')
        plt.legend(loc='upper left', bbox_to_anchor=(1.02, 1))
        output_dir = 'output_data'
        plt.savefig(os.path.join(output_dir, f"tes_stored.png"), bbox_inches='tight')