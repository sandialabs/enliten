    def LCOE_metrics(self, metrics):
        def augment_array_np(arr, L):
            arr_with_zero = np.insert(arr, 0, 0)
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
        
            for v in range(1, analysis_period + 1):
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
        system_annual_OM_USD = metrics['system_annual_OM_USD']  # Annual O&M costs in USD
        system_annual_VOM_USD = np.array(metrics['system_to_load_annual_MWh_e']) * 1000 * self.VOM
        metrics['system_annual_VOM_USD'] = system_annual_VOM_USD
        analysis_period = self.analysis_period  # Analysis period in years
        WACC_n = self.DF*self.I*(1-tax) + (1-self.DF)*self.COE # use in LCOE calcs for "nominal" LCOE
        # WACC_n = 0.07
        WACC_r = ((1+WACC_n)/(1+inflation))-1 # use in LCOE calcs for "real" LCOE
        CRF = WACC_r / (1 - (1 + WACC_r)**(-analysis_period))
    
        # ===============================================================================================
        # Define Revenue, Cost, and Other Cash Flow Arrays 
        # ===============================================================================================
        annual_OM = np.array([system_annual_OM_USD * ((1 + esc)**(v + 1)) for v in range(analysis_period)])
        annual_OM = np.insert(annual_OM,0,0)
    
        annual_VOM = np.array([system_annual_VOM_USD * ((1 + esc)**(v + 1)) for v in range(analysis_period)])
        annual_VOM = np.insert(annual_VOM,0,0)
    
        if len(self.tes_systems) == 0:
            annual_fuel = [0]
            annual_fuel = augment_array_np(np.array(annual_fuel), analysis_period + 1)  
        else:
            annual_fuel_kg = np.array(metrics['TES_System_to_load_MWh_gas_kg']) 
            annual_fuel = annual_fuel_kg * 0.0353 * gas_cost # Natural Gas
            # annual_fuel = annual_fuel_kg * 0.03456 * gas_cost # RFO
            metrics['annual_fuel_cost_USD'] = annual_fuel
            annual_fuel = np.array([annual_fuel * ((1 + esc)**(v + 1)) for v in range(analysis_period)])
            annual_fuel = np.insert(annual_fuel,0,0)
        
        if self.total_project_cost == False:
            annual_renewables = np.array(metrics['system_to_load_annual_MWh_e']) * 1000
            
            # annual_electricity_sales = annual_renewables * self.e_sale # standard analysis (sole load type)
            # annual_electricity_sales = (metrics['export_energy_MWh_e']*self.e_sale * 1000) + (250125-metrics['annual_fuel_cost_USD'])# C&E analysis
            annual_electricity_sales = (np.array(metrics['annual_grid_energy_cost_base']) + np.array(metrics['annual_demand_charge_cost_base'])) - (np.array(metrics['annual_grid_energy_cost']) + np.array(metrics['annual_demand_charge_cost'])) # Avoided ASGARD Costs
            
            annual_renewables = [annual_renewables.item()]
            annual_renewables = np.ones_like(range(analysis_period))*annual_renewables
            annual_renewables = np.insert(annual_renewables,0,0)
    
            metrics['annual_electricity_sales_USD'] = annual_electricity_sales
            annual_electricity_sales = np.array([annual_electricity_sales * ((1 + 0)**(v + 1)) for v in range(analysis_period)])
            annual_electricity_sales = np.insert(annual_electricity_sales,0,0)
    
            metrics['annual_grid_energy_cost'] = 0
            metrics['annual_demand_charge_cost'] = 0
            annual_electricity_purchases = np.array(metrics['annual_grid_energy_cost']) + np.array(metrics['annual_demand_charge_cost'])
            metrics['annual_electricity_purchases_USD'] = annual_electricity_purchases
            annual_electricity_purchases = np.array([annual_electricity_purchases * ((1 + 0)**(v + 1)) for v in range(analysis_period)])
            annual_electricity_purchases = np.insert(annual_electricity_purchases,0,0)
            
        else:
            annual_renewables = np.array(metrics['system_to_load_annual_MWh_e']) * 1000 + np.array(metrics['grid_to_load_MWh_e']) * 1000
            annual_renewables = [annual_renewables.item()]
            annual_renewables = np.ones_like(range(analysis_period))*annual_renewables
            annual_renewables = np.insert(annual_renewables,0,0)
    
            annual_electricity_sales = (np.array(metrics['system_to_load_annual_MWh_e']) * 1000) * self.e_sale    
            metrics['annual_electricity_sales_USD'] = annual_electricity_sales
            annual_electricity_sales = np.array([annual_electricity_sales * ((1 + 0)**(v + 1)) for v in range(analysis_period)])
            annual_electricity_sales = np.insert(annual_electricity_sales,0,0)
    
            annual_electricity_purchases = np.array(metrics['annual_grid_energy_cost']) + np.array(metrics['annual_demand_charge_cost'])
            metrics['annual_electricity_purchases_USD'] = annual_electricity_purchases
            annual_electricity_purchases = np.array([annual_electricity_purchases * ((1 + 0)**(v + 1)) for v in range(analysis_period)])
            annual_electricity_purchases = np.insert(annual_electricity_purchases,0,0)
    
        add = np.zeros(analysis_period + 1)
        for bes in self.bes_systems:
            add = add + np.array(augment_array_np(np.array(bes.cpx_batt_aug_annual),analysis_period + 1)[:analysis_period + 1])
        aug_batt = add
        metrics['system_cpx_batt_aug_annual'] = list(aug_batt)
        
        add = np.zeros(analysis_period + 1)
        for tes in self.tes_systems:
            add = add + np.array(augment_array_np(np.array(tes.cpx_htr_aug_annual),analysis_period + 1)[:analysis_period +1 ])
        aug_htr = add
        metrics['system_cpx_htr_aug_annual'] = list(aug_htr)
        
        # ================================================================================================
        # Main TEA CALCULATIONS
        # ================================================================================================
        depreciation_values, depreciable_fractions = calculate_depreciation(
        analysis_period, system_capex_USD * (1-grant_percentage), inflation, depreciation_period, ITC
        )
    
        # Calculate Present Value of Depreciation (PVD)
        PVD = sum([
            depreciable_fractions[n] / (1 + WACC_r)**(n)
            for n in range(0, depreciation_period + 1)
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
        # FCR_before_tax_revenue_required = 0.284
        
        NPV_OM_N = npf.npv(WACC_r,annual_OM[:analysis_period + 1])
        NPV_VOM_N = npf.npv(WACC_r,annual_VOM[:analysis_period + 1])
        NPV_depreciation = npf.npv(WACC_r, depreciation_values)
        NPV_Energy_N = npf.npv(WACC_r, annual_renewables[:analysis_period + 1])
        NPV_depreciation = npf.npv(WACC_r, depreciation_values)
        NPV_electricity_sales_N = npf.npv(WACC_r, annual_electricity_sales[:analysis_period + 1])
        NPV_electricity_purchases_N = npf.npv(WACC_r, annual_electricity_purchases[:analysis_period + 1])
        NPV_fuel_purchases_N = npf.npv(WACC_r, annual_fuel[:analysis_period + 1])
        NPV_aug_batt_N = npf.npv(WACC_r, aug_batt[:analysis_period + 1])
        NPV_aug_htr_N = npf.npv(WACC_r, aug_htr[:analysis_period + 1])
        
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
        annualized_aug_batt_BT = NPV_aug_batt_N * CRF
        annualized_aug_batt_AT = NPV_aug_batt_N * CRF * (1-tax)
        
        annual_ARR_AT = (annualized_CAPEX_AT + annualized_OM_AT + annualized_VOM_AT + annualized_fuel_AT +
                         annualized_electricity_purchases_AT + annualized_aug_batt_AT + annualized_aug_htr_AT)
        
        annual_ARR_BT = (annualized_CAPEX_BT + annualized_OM_BT + annualized_VOM_BT + annualized_fuel_BT +
                         annualized_electricity_purchases_BT + annualized_aug_batt_BT + annualized_aug_htr_BT)
        
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
        
        for v in range(1, analysis_period + 1):
            OM_esc = annual_OM[v] + annual_VOM[v]
            ebit = (annual_electricity_sales[v]) - (
                OM_esc + annual_fuel[v] + annual_electricity_purchases[v] + aug_batt[v] + aug_htr[v]
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
            costs.append(OM_esc + annual_fuel[v] + annual_electricity_purchases[v] + aug_batt[v] + aug_htr[v])
            other_tax.append(insurance * system_capex_USD * (1 - grant_percentage) + property_tax * system_capex_USD * (1 - grant_percentage))
            taxes_array.append(taxes)
            taxable_income_array.append(taxable_income)
            annual_cash_flow.append(net_income)
        
        # Calculate IRR and TLCC
        NPV_costs = npf.npv(WACC_r, costs)
        NPV_other_tax = npf.npv(WACC_r, other_tax)
        NPV_cash_flow = npf.npv(WACC_r, annual_cash_flow)
        IRR = npf.irr(annual_cash_flow)
        
        after_tax_TLCC = -1 * annual_cash_flow[0] - (tax * NPV_depreciation) + ((1 - tax) * NPV_costs) + ((1-tax) * NPV_other_tax)
        before_tax_TLCC = (-1 * annual_cash_flow[0] - (tax * NPV_depreciation) + ((1 - tax) * NPV_costs)) / (1-tax) + (NPV_other_tax) / (1-tax)
        
        # Solve for after & before tax LCOE
        LCOE_after_tax = after_tax_TLCC / NPV_Energy_N
        LCOE_before_tax = before_tax_TLCC / NPV_Energy_N
        
        # LCOE calculation
        ARR_AT_array = [0] + [annual_ARR_AT] * analysis_period
        ARR_BT_array = [0] + [annual_ARR_BT] * analysis_period
        
        # Calculate NPV for ARR_AT and ARR_BT
        NPV_ARR_AT = npf.npv(WACC_r, ARR_AT_array)
        LCOE_real_USD_kWh_AT = NPV_ARR_AT / NPV_Energy_N
        
        NPV_ARR_BT = npf.npv(WACC_r, ARR_BT_array)
        LCOE_real_USD_kWh_BT = NPV_ARR_BT / NPV_Energy_N
    
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