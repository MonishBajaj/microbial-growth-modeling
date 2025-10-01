
import numpy as np
from scipy.interpolate import CubicSpline

class CorrectedMicrobialGrowthModel:
  

    def __init__(self):
        """Initialize with Baranyi-Roberts model parameters"""
        # Primary model parameters [y0, ymax, h0]
        self.primod = [2.51, 8.0, 1.07]

        # Secondary model parameters [Tmin_C, Tmax_C, a, b]  
        self.secmod = [-1.6081, 35.1581, 0.0005, 4.7509]

        # Extract parameters
        self.Tmin_C = self.secmod[0]
        self.Tmax_C = self.secmod[1] 
        self.a = self.secmod[2]
        self.b = self.secmod[3]

        self.y0 = self.primod[0]
        self.ymax = self.primod[1]
        self.h0 = self.primod[2]

        # Time step configuration (CRITICAL: matches MATLAB)
        self.dt_min = 1  # minutes
        self.dth = self.dt_min / 60  # hours (0.0167 hours = 1 minute)

    def secondary_model(self, temperature):
        """Calculate maximum specific growth rate based on temperature"""
        if temperature >= 15:
            mumax = self.a * (temperature - self.Tmin_C)**2 * (1 - np.exp(self.b * (temperature - self.Tmax_C)))
        else:
            mumax = 0
        return max(mumax, 0)

    def simulate_growth(self, time_hours_coarse, temperatures_coarse):
        """
        Main simulation function - CORRECTED VERSION

        This now matches MATLAB's approach:
        1. Takes coarse input data (e.g., hourly)
        2. Creates fine time grid (1-minute resolution)  
        3. Interpolates temperature to fine grid
        4. Runs simulation on fine grid for accurate integration

        Parameters:
        time_hours_coarse: Input time points (can be hourly)
        temperatures_coarse: Corresponding temperatures

        Returns:
        dict: Complete simulation results on fine time grid
        """

        # Step 1: Create fine time grid (MATLAB's approach)
        # This is the KEY FIX - MATLAB uses 1-minute resolution
        tt_fine = np.arange(time_hours_coarse[0], time_hours_coarse[-1] + self.dth, self.dth)

        # Step 2: Interpolate temperature to fine grid using cubic splines
        T_interp = CubicSpline(time_hours_coarse, temperatures_coarse)
        TT_fine = T_interp(tt_fine)

        n = len(tt_fine)

        # Step 3: Solve for Q (physiological state) using RK4
        # Create superfine grid for RK4 accuracy (oversample by factor of 2)
        t_superfine = np.linspace(tt_fine[0], tt_fine[-1], 2*n-1)
        T_interp_super = CubicSpline(tt_fine, TT_fine)
        T_superfine = T_interp_super(t_superfine)

        # Calculate growth rates on superfine grid
        mumax_superfine = np.array([self.secondary_model(T) for T in T_superfine])

        # Initialize Q
        alpha = np.exp(-self.h0)
        q0 = 1 / (np.exp(self.h0) - 1)
        Q = np.zeros(n)
        Q[0] = np.log(q0)

        # RK4 integration for Q
        for j in range(1, n):
            i = 2 * (j - 1)

            k1 = self.dth * mumax_superfine[i] if i < len(mumax_superfine) else 0
            k2 = self.dth * mumax_superfine[i + 1] if i + 1 < len(mumax_superfine) else k1
            k3 = k2
            k4 = self.dth * mumax_superfine[i + 2] if i + 2 < len(mumax_superfine) else k2

            Q[j] = Q[j-1] + (1/6) * (k1 + 2*k2 + 2*k3 + k4)

        # Step 4: Solve for y (population) using RK4
        # Interpolate Q to superfine grid
        Q_interp = CubicSpline(tt_fine, Q)  
        Q_superfine = Q_interp(t_superfine)

        # Initialize population
        y = np.zeros(n)
        y[0] = self.y0

        # RK4 integration for population
        for j in range(1, n):
            i = 2 * (j - 1)

            # Calculate physiological state factors
            alpha_i = 1 / (1 + np.exp(-Q_superfine[i])) if i < len(Q_superfine) else 0
            alpha_i1 = 1 / (1 + np.exp(-Q_superfine[i + 1])) if i + 1 < len(Q_superfine) else alpha_i
            alpha_i2 = 1 / (1 + np.exp(-Q_superfine[i + 2])) if i + 2 < len(Q_superfine) else alpha_i1

            # Capacity limitation factor
            capacity_factor = 1 - np.exp(y[j-1] - self.ymax)

            # RK4 coefficients
            k1 = self.dth * mumax_superfine[i] * alpha_i * capacity_factor if i < len(mumax_superfine) else 0

            capacity_factor_k2 = 1 - np.exp((y[j-1] + k1/2) - self.ymax)
            k2 = self.dth * mumax_superfine[i + 1] * alpha_i1 * capacity_factor_k2 if i + 1 < len(mumax_superfine) else k1

            capacity_factor_k3 = 1 - np.exp((y[j-1] + k2/2) - self.ymax)
            k3 = self.dth * mumax_superfine[i + 1] * alpha_i1 * capacity_factor_k3 if i + 1 < len(mumax_superfine) else k2

            capacity_factor_k4 = 1 - np.exp((y[j-1] + k3) - self.ymax)
            k4 = self.dth * mumax_superfine[i + 2] * alpha_i2 * capacity_factor_k4 if i + 2 < len(mumax_superfine) else k3

            y[j] = y[j-1] + (1/6) * (k1 + 2*k2 + 2*k3 + k4)

        return {
            'time': tt_fine,              # Fine time grid (1-minute resolution)
            'temperature': TT_fine,       # Temperature on fine grid 
            'population': y,              # Population prediction
            'physiological_state': Q,     # Q values
            'time_coarse': time_hours_coarse,      # Original coarse input
            'temperature_coarse': temperatures_coarse  # Original coarse input
        }
