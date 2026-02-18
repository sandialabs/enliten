import numpy_financial as npf
import numpy as np

class LCOECalculator:
    def __init__(self, system_capex_USD, system_annual_OM_USD, system_annual_VOM_USD, system_to_load_annual_MWh_e, system_augment, ITC = 0.5, DF = 0.5, COE = 0.13, I = 0.08, grant_percentage = 0, tax = 0.257, inflation = 0.028, property_tax = 0.0084, insurance = 0.004, depreciation_period = 5, esc = 0.028, analysis_period = 30, VOM = 0.003, e_sale = 0.07):

        """
        LCOECalculator initialzies the class allowing all the functions to calculate the LCOE and other TEA metrics
        
        Parameters
        ----------
        system_capex_USD : float
            Total system capital expenditure. [USD]
            
        system_annual_OM_USD : float
            Annual fixed O&M costs. [USD]
            
        system_annual_VOM_USD : float
            Annual variable O&M costs. [USD]
        
        system_to_load_annual_MWh_e : float
            Annual renewable energy production. [MWh]
        
        system_augment (list)
            Additional system costs over the analysis period. [USD]
        
        ITC : float
            Investment Tax Credit. [%]
        
        DF : float
            Debt Fraction, fraction of capital financed with debt. [%]
        
        COE : float
            Cost of Equity, assumed rate of return on equity-financed assets. [%]
        
        I : float
            Interest rate on debt. [%]
        
        grant_percentage : float
            Grant percentage, reduces upfront capital costs. [%]
        
        tax : float
            Combined state and federal tax rate. [%]
        
        inflation : float
            Inflation rate.	[%]
        
        property_tax : float
            Property tax rate. [%]
        
        insurance : float
            Insurance rate.	[%]
        
        depreciation_period : int
            Depreciation period. [Years]
        
        esc : float
            Escalation rate for O&M costs.	[%]
        
        analysis_period : int
            Analysis period. [Years]
        
        VOM : float
            Variable O&M cost per kWh [kWh]
        
        e_sale : float
            Electricity sale price per kWh. [kWh]
        
        """
        self.system_capex_USD = system_capex_USD
        self.system_annual_OM_USD = system_annual_OM_USD
        self.system_annual_VOM_USD = system_annual_VOM_USD
        self.system_to_load_annual_MWh_e = system_to_load_annual_MWh_e   
        self.system_augment = system_augment
        self.ITC = ITC
        self.DF = DF
        self.COE = COE
        self.I = I
        self.grant_percentage = grant_percentage
        self.tax = tax
        self.inflation = inflation
        self.property_tax = property_tax
        self.insurance = insurance
        self.depreciation_period = depreciation_period
        self.esc = esc
        self.analysis_period = analysis_period
        self.VOM = VOM
        self.e_sale = e_sale


    def augment_array_np(self, arr, L):
        """
        Augment an array to match a specified length by repeating its values.

        Parameters:
        - arr: Input array to be augmented.
        - L: Desired length of the output array.

        Returns:
        - Augmented array with length L.
        """
        arr_with_zero = np.insert(arr, 0, 0)  # Insert a zero at the beginning of the array
        l_val = arr_with_zero.size
        if L > l_val:
            shortfall = L - l_val
            repeat_times = (shortfall + l_val - 1) // l_val
            repeated_section = np.tile(arr_with_zero, (repeat_times,))[-shortfall:]
            augmented_array = np.concatenate((arr_with_zero, repeated_section))
            return augmented_array
        else:
            return arr_with_zero[:L]
    
    def calculate_depreciation(self, analysis_period = None, system_capex_USD = None, inflation = None, depreciation_period = None, ITC = None):

        """
        Calculate depreciation values and fractions.

        Parameters:
        - Certain class variables

        Returns:
        depreciation_values: List
            Depreciation values for each year. [$]
            
        depreciable_fractions: List
            Depreciable fractions for each year. [%]
        """

        # Sets variables to initialized class value
        if analysis_period == None:
            analysis_period = self.analysis_period
        if system_capex_USD == None:
            system_capex_USD = self.system_capex_USD
        if inflation == None:
            inflation = self.inflation
        if depreciation_period == None:
            depreciation_period = self.depreciation_period
        if ITC == None:
            ITC = self.ITC
        
        # Variables for calculations
        adjusted_depreciable_base = system_capex_USD * (1 - ITC / 2)
        straight_line_rate = 1 / depreciation_period
        double_declining_rate = 2 * straight_line_rate
        depreciation_values = [0]  # Year 0 has no depreciation
        depreciable_fractions = [0]  # Year 0 fraction is 0
        remaining_book_value = adjusted_depreciable_base

        # Calculates depreciation values and fractions
        for v in range(1, analysis_period + 1):
            if v <= depreciation_period:
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



    def calculate_lcoe_metrics(self, system_capex_USD = None, system_annual_OM_USD = None, system_annual_VOM_USD = None, system_to_load_annual_MWh_e = None, system_augment = None, ITC = None, DF = None, COE = None, I = None, grant_percentage = None, tax  = None, inflation = None, property_tax = None, insurance = None, depreciation_period = None, esc = None, analysis_period = None, VOM = None, e_sale = None, gas_cost = None):

        """
        Calculate LCOE metrics.

        Parameters:
        - Same as class

        Returns:
        - metrics: 
            Dictionary with LCOE metrics.
        """

        if system_capex_USD is None:
            system_capex_USD = self.system_capex_USD
        if system_annual_OM_USD is None:
            system_annual_OM_USD = self.system_annual_OM_USD
        if system_annual_VOM_USD is None:
            system_annual_VOM_USD = self.system_annual_VOM_USD
        if system_to_load_annual_MWh_e is None:
            system_to_load_annual_MWh_e = self.system_to_load_annual_MWh_e
        if system_augment is None:
            system_augment = self.system_augment
        if ITC is None:
            ITC = self.ITC
        if DF is None:
            DF = self.DF
        if COE is None:
            COE = self.COE
        if I is None:
            I = self.I
        if grant_percentage is None:
            grant_percentage = self.grant_percentage
        if tax is None:
            tax = self.tax
        if inflation is None:
            inflation = self.inflation
        if property_tax is None:
            property_tax = self.property_tax
        if insurance is None:
            insurance = self.insurance
        if depreciation_period is None:
            depreciation_period = self.depreciation_period
        if esc is None:
            esc = self.esc
        if analysis_period is None:
            analysis_period = self.analysis_period
        if VOM is None:
            VOM = self.VOM
        if e_sale is None:
            e_sale = self.e_sale      
        
        metrics = {}

        # Discount Rate Setup
        WACC_n = DF * I * (1 - tax) + (1 - DF) * COE
        WACC_r = ((1 + WACC_n) / (1 + inflation)) - 1        
        CRF = WACC_r / (1 - (1 + WACC_r)**(-analysis_period))

        # Annual O&M and VOM costs
        annual_OM = np.array([system_annual_OM_USD * ((1 + esc)**(v + 1)) for v in range(analysis_period)])
        annual_OM = np.insert(annual_OM, 0, 0)
        annual_VOM = np.array([system_annual_VOM_USD * ((1 + esc)**(v + 1)) for v in range(analysis_period)])
        annual_VOM = np.insert(annual_VOM, 0, 0)
        
        # Annual electricity purchases
        annual_electricity_purchases = np.array(0) + np.array(0)
        metrics['annual_electricity_purchases_USD'] = annual_electricity_purchases
        annual_electricity_purchases = np.array([annual_electricity_purchases * ((1 + esc)**(v + 1)) for v in range(analysis_period)])
        annual_electricity_purchases = np.insert(annual_electricity_purchases,0,0)

        # Renewable energy production
        annual_renewables = np.array(system_to_load_annual_MWh_e) * 1000
        annual_renewables = [annual_renewables.item()]
        annual_renewables = np.ones_like(range(analysis_period)) * annual_renewables
        annual_renewables = np.insert(annual_renewables, 0, 0)

        # Annual electricity sales
        annual_electricity_sales = np.array(system_to_load_annual_MWh_e) * 1000 * e_sale
        metrics['annual_electricity_sales_USD'] = annual_electricity_sales
        annual_electricity_sales = np.array([annual_electricity_sales * ((1 + 0)**(v + 1)) for v in range(analysis_period)])
        annual_electricity_sales = np.insert(annual_electricity_sales, 0, 0)

        # Depreciation
        depreciation_values, depreciable_fractions = self.calculate_depreciation(
            analysis_period, system_capex_USD * (1 - grant_percentage), inflation, depreciation_period, ITC
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

        # Net Present Values (NPV)
        NPV_OM_N = npf.npv(WACC_r, annual_OM[:analysis_period + 1])
        NPV_VOM_N = npf.npv(WACC_r, annual_VOM[:analysis_period + 1])
        NPV_depreciation = npf.npv(WACC_r, depreciation_values)
        NPV_Energy_N = npf.npv(WACC_r, annual_renewables[:analysis_period + 1])
        NPV_electricity_sales_N = npf.npv(WACC_r, annual_electricity_sales[:analysis_period + 1])
        NPV_electricity_purchases_N = npf.npv(WACC_r, annual_electricity_purchases[:analysis_period + 1])
        NPV_system_augment_N = npf.npv(WACC_r, system_augment[:analysis_period + 1])


        # Annualized costs
        annualized_CAPEX_AT = (1 - grant_percentage) * system_capex_USD * FCR_after_tax_deduction
        annualized_CAPEX_BT = (1 - grant_percentage) * system_capex_USD * FCR_before_tax_revenue_required
        annualized_OM_BT = NPV_OM_N * CRF
        annualized_OM_AT = NPV_OM_N * CRF * (1 - tax)
        annualized_VOM_BT = NPV_VOM_N * CRF
        annualized_VOM_AT = NPV_VOM_N * CRF * (1 - tax)
        annualized_electricity_purchases_BT = NPV_electricity_purchases_N * CRF
        annualized_electricity_purchases_AT = NPV_electricity_purchases_N * CRF * (1-tax)
        annualized_electricity_sales_BT = NPV_electricity_sales_N * CRF
        annualized_electricity_sales_AT = NPV_electricity_sales_N * CRF * (1 - tax) 
        annualized_system_augment_BT = NPV_system_augment_N * CRF
        annualized_system_augment_AT = NPV_system_augment_N * CRF * (1-tax)
        annual_ARR_AT = (annualized_CAPEX_AT + annualized_OM_AT + annualized_VOM_AT + annualized_electricity_purchases_AT + annualized_system_augment_AT)
        annual_ARR_BT = (annualized_CAPEX_BT + annualized_OM_BT + annualized_VOM_BT + annualized_electricity_purchases_BT + annualized_system_augment_BT)

        # Track revenues, costs, and taxes
        revenues = [0]
        costs = [0]
        other_tax = [0]
        taxable_income_array = [0]
        taxes_array = [0]
        annual_cash_flow = [-(system_capex_USD * (1 - ITC) * (1 - grant_percentage))]  # Initial equity investment
        unused_depreciation = 0  # Initialize unused depreciation rollover

        # C&E Analysis
        for v in range(1, analysis_period + 1):
            OM_esc = annual_OM[v] + annual_VOM[v]
            ebit = (annual_electricity_sales[v]) - (
                OM_esc + annual_electricity_purchases[v] + system_augment[v]
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
            costs.append(OM_esc + annual_electricity_purchases[v]+ system_augment[v]
            )
            other_tax.append(insurance * system_capex_USD * (1 - grant_percentage) + property_tax * system_capex_USD * (1 - grant_percentage))
            taxes_array.append(taxes)
            taxable_income_array.append(taxable_income)
            annual_cash_flow.append(net_income)

        # Calculate IRR and TLCC    
        NPV_costs = npf.npv(WACC_r, costs)
        NPV_other_tax = npf.npv(WACC_r, other_tax)
        NPV_cash_flow = npf.npv(WACC_r, annual_cash_flow)
        IRR = npf.irr(annual_cash_flow)
        
        # Total Lifecycle Costs (TLCC)
        after_tax_TLCC = -1 * annual_cash_flow[0] - (tax * NPV_depreciation) + ((1 - tax) * NPV_costs) + ((1 - tax) * NPV_other_tax)
        before_tax_TLCC = (-1 * annual_cash_flow[0] - (tax * NPV_depreciation) + ((1 - tax) * NPV_costs)) / (1 - tax) + (NPV_other_tax) / (1 - tax)

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
        metrics['LCOE_real_USD_kWh_BT'] = LCOE_real_USD_kWh_BT
        metrics['LCOE_real_USD_kWh_AT'] = LCOE_real_USD_kWh_AT
        return metrics