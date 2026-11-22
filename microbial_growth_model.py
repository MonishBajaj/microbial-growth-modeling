"""
Earlier Baranyi-Roberts model with one fixed Pseudomonas coefficient set.

The web app uses corrected_microbial_growth_model.py, which loads coefficients
from pmp_catalog.py and builds a one-minute grid before integrating. This file
is what example_usage.py still imports. Its secondary_model returns 0 below 15 C.
"""

import numpy as np
from scipy.interpolate import CubicSpline

class MicrobialGrowthModel:
    """
    Implementation of the Baranyi-Roberts microbial growth model
    Equivalent to the MATLAB implementation but with improved structure
    """

    def __init__(self):
        """Initialize the microbial growth model with Baranyi parameters"""
        # Primary model parameters [y0, ymax, h0]
        self.primod = [2.51, 8.0, 1.07]

        # Secondary model parameters [Tmin_C, Tmax_C, a, b]
        self.secmod = [-1.6081, 35.1581, 0.0005, 4.7509]

        # Extract parameters for easier use
        self.Tmin_C = self.secmod[0]
        self.Tmax_C = self.secmod[1] 
        self.a = self.secmod[2]
        self.b = self.secmod[3]

        self.y0 = self.primod[0]
        self.ymax = self.primod[1]
        self.h0 = self.primod[2]

        # Time step configuration
        self.dt_min = 1  # minutes
        self.dth = self.dt_min / 60  # hours

    def secondary_model(self, temperature):
        """
        Calculate maximum specific growth rate based on temperature

        Parameters:
        temperature: Temperature in Celsius

        Returns:
        mumax: Maximum specific growth rate
        """
        if temperature >= 15:
            mumax = self.a * (temperature - self.Tmin_C)**2 * (1 - np.exp(self.b * (temperature - self.Tmax_C)))
        else:
            mumax = 0
        return max(mumax, 0)  # Ensure non-negative

    def runge_kutta_4_Q(self, tt, TT):
        """
        Solve for Q (physiological state) using 4th order Runge-Kutta

        Parameters:
        tt: Time vector (hours)
        TT: Temperature vector (Celsius)

        Returns:
        Q: Physiological state vector
        t_fine: Fine time grid for RK4
        mumax_fine: Growth rates on fine grid
        """
        n = len(TT)

        # Create fine grid for RK4 (oversample by factor of 2)
        t_fine = np.linspace(tt[0], tt[-1], 2*n-1)
        T_interp = CubicSpline(tt, TT)
        T_fine = T_interp(t_fine)

        # Calculate growth rates on fine grid
        mumax_fine = np.array([self.secondary_model(T) for T in T_fine])

        # Initialize Q
        alpha = np.exp(-self.h0)
        q0 = 1 / (np.exp(self.h0) - 1)
        Q = np.zeros(n)
        Q[0] = np.log(q0)

        # RK4 algorithm for Q
        for j in range(1, n):
            i = 2 * (j - 1)  # Index for fine grid

            # RK4 coefficients
            k1 = self.dth * mumax_fine[i]
            k2 = self.dth * mumax_fine[i + 1] if i + 1 < len(mumax_fine) else k1
            k3 = k2
            k4 = self.dth * mumax_fine[i + 2] if i + 2 < len(mumax_fine) else k2

            # Update Q
            Q[j] = Q[j-1] + (1/6) * (k1 + 2*k2 + 2*k3 + k4)

        return Q, t_fine, mumax_fine

    def runge_kutta_4_y(self, tt, TT, Q):
        """
        Solve for y (population) using 4th order Runge-Kutta

        Parameters:
        tt: Time vector (hours)
        TT: Temperature vector (Celsius)
        Q: Physiological state vector

        Returns:
        y: Population vector (Log CFU/g)
        """
        n = len(TT)

        # Create fine grid and interpolate Q and temperature
        t_fine = np.linspace(tt[0], tt[-1], 2*n-1)
        T_interp = CubicSpline(tt, TT)
        Q_interp = CubicSpline(tt, Q)

        T_fine = T_interp(t_fine)
        Q_fine = Q_interp(t_fine)

        # Calculate growth rates on fine grid
        mumax_fine = np.array([self.secondary_model(T) for T in T_fine])

        # Initialize population
        y = np.zeros(n)
        y[0] = self.y0

        # RK4 algorithm for population
        for j in range(1, n):
            i = 2 * (j - 1)  # Index for fine grid

            # Growth rate components at different points
            alpha_i = 1 / (1 + np.exp(-Q_fine[i]))
            alpha_i1 = 1 / (1 + np.exp(-Q_fine[i + 1])) if i + 1 < len(Q_fine) else alpha_i
            alpha_i2 = 1 / (1 + np.exp(-Q_fine[i + 2])) if i + 2 < len(Q_fine) else alpha_i1

            # Capacity limitation factor
            capacity_factor = 1 - np.exp(y[j-1] - self.ymax)

            # RK4 coefficients
            k1 = self.dth * mumax_fine[i] * alpha_i * capacity_factor

            capacity_factor_k2 = 1 - np.exp((y[j-1] + k1/2) - self.ymax)
            k2 = self.dth * mumax_fine[i + 1] * alpha_i1 * capacity_factor_k2 if i + 1 < len(mumax_fine) else k1

            capacity_factor_k3 = 1 - np.exp((y[j-1] + k2/2) - self.ymax)
            k3 = self.dth * mumax_fine[i + 1] * alpha_i1 * capacity_factor_k3 if i + 1 < len(mumax_fine) else k2

            capacity_factor_k4 = 1 - np.exp((y[j-1] + k3) - self.ymax)
            k4 = self.dth * mumax_fine[i + 2] * alpha_i2 * capacity_factor_k4 if i + 2 < len(mumax_fine) else k3

            # Update population
            y[j] = y[j-1] + (1/6) * (k1 + 2*k2 + 2*k3 + k4)

        return y

    def simulate_growth(self, time_hours, temperatures):
        """
        Main simulation function - equivalent to main MATLAB code

        Parameters:
        time_hours: Array of time points in hours
        temperatures: Array of temperatures in Celsius

        Returns:
        dict: Complete simulation results
        """
        # Ensure consistent time grid
        tt = np.array(time_hours)

        # Interpolate temperatures if needed
        if len(temperatures) != len(time_hours):
            temp_interp = CubicSpline(time_hours, temperatures)
            TT = temp_interp(tt)
        else:
            TT = np.array(temperatures)

        # Solve for physiological state Q
        Q, t_fine, mumax_fine = self.runge_kutta_4_Q(tt, TT)

        # Solve for population y
        y_pred = self.runge_kutta_4_y(tt, TT, Q)
        print (y_pred)
        return {
            'time': tt,
            'temperature': TT,
            'population': y_pred,
            'physiological_state': Q,
            'growth_rate': mumax_fine,
            'time_fine': t_fine
        }
