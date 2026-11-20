"""Baranyi–Roberts growth under a dynamic temperature profile.

Supports the project’s legacy Pseudomonas secondary model and Ratkowsky-style
square-root EGR models (log10 CFU/h) used for verified cooling entries.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline

from pmp_catalog import DEFAULT_MODEL_ID, get_model, require_ready


class CorrectedMicrobialGrowthModel:

    def __init__(self, model_id=None, coeffs=None, meta=None):
        """Initialize with catalog coefficients or the legacy MATLAB-matched set.

        Prefer ``from_catalog(model_id)``. Passing nothing keeps prior behaviour.
        """
        if coeffs is None:
            entry = get_model(DEFAULT_MODEL_ID)
            coeffs = entry['coeffs']
            meta = entry
            model_id = DEFAULT_MODEL_ID

        self.model_id = model_id or DEFAULT_MODEL_ID
        self.meta = meta or {}
        self.coeffs = dict(coeffs)

        self.secondary = self.coeffs.get('secondary', 'legacy_quadratic')
        self.Tmin_C = float(self.coeffs['Tmin_C'])
        self.Tmax_C = float(self.coeffs['Tmax_C'])
        self.a = float(self.coeffs['a'])
        self.b = float(self.coeffs['b'])
        self.y0 = float(self.coeffs['y0'])
        self.ymax = float(self.coeffs['ymax'])
        self.h0 = float(self.coeffs['h0'])
        floor = self.coeffs.get('growth_floor_C')
        self.growth_floor_C = None if floor is None else float(floor)

        # Time step configuration (CRITICAL: matches MATLAB for legacy model)
        self.dt_min = 1  # minutes
        self.dth = self.dt_min / 60  # hours

        # Back-compat aliases used by older call sites / notebooks
        self.primod = [self.y0, self.ymax, self.h0]
        self.secmod = [self.Tmin_C, self.Tmax_C, self.a, self.b]

    @classmethod
    def from_catalog(cls, model_id):
        """Build a model from a ready catalog entry, or raise ValueError."""
        entry, err = require_ready(model_id)
        if err:
            raise ValueError(err)
        return cls(model_id=model_id, coeffs=entry['coeffs'], meta=entry)

    def secondary_model(self, temperature):
        """Return μ_max in log10 CFU per hour for one temperature."""
        t = float(temperature)
        if self.growth_floor_C is not None and t < self.growth_floor_C:
            return 0.0
        if t <= self.Tmin_C or t >= self.Tmax_C:
            return 0.0

        if self.secondary == 'legacy_quadratic':
            # Historical project form (Pseudomonas / MATLAB match):
            # μ = a * (T - Tmin)^2 * (1 - exp(b * (T - Tmax)))
            mumax = self.a * (t - self.Tmin_C) ** 2 * (1.0 - np.exp(self.b * (t - self.Tmax_C)))
            return float(max(mumax, 0.0))

        if self.secondary == 'ratkowsky_sqrt_egr':
            # Juneja (2001) Table 3 / Eq. (1) family, written so EGR matches
            # Table 4 near Tmax:
            #   sqrt(EGR) = a*(T-Tmin)*sqrt(1-exp(b*(T-Tmax)))
            #   EGR = [a*(T-Tmin)]^2 * (1-exp(b*(T-Tmax)))
            # with EGR in log10(CFU)/h.
            inside = 1.0 - np.exp(self.b * (t - self.Tmax_C))
            if inside <= 0:
                return 0.0
            mumax = (self.a * (t - self.Tmin_C)) ** 2 * inside
            return float(max(mumax, 0.0))

        raise ValueError(f'Unknown secondary model: {self.secondary}')

    def simulate_growth(self, time_hours_coarse, temperatures_coarse):
        """
        Main simulation function - CORRECTED VERSION

        This now matches MATLAB's approach:
        1. Takes coarse input data (e.g., hourly)
        2. Creates fine time grid (1-minute resolution)
        3. Interpolates temperature to fine grid
        4. Runs simulation on fine grid for accurate integration
        """
        time_hours_coarse = np.asarray(time_hours_coarse, dtype=float)
        temperatures_coarse = np.asarray(temperatures_coarse, dtype=float)
        if time_hours_coarse.size < 2:
            raise ValueError('Need at least two temperature samples.')

        tt_fine = np.arange(time_hours_coarse[0], time_hours_coarse[-1] + self.dth, self.dth)
        T_interp = CubicSpline(time_hours_coarse, temperatures_coarse)
        TT_fine = T_interp(tt_fine)

        n = len(tt_fine)

        t_superfine = np.linspace(tt_fine[0], tt_fine[-1], 2 * n - 1)
        T_interp_super = CubicSpline(tt_fine, TT_fine)
        T_superfine = T_interp_super(t_superfine)

        mumax_superfine = np.array([self.secondary_model(T) for T in T_superfine])

        q0 = 1 / (np.exp(self.h0) - 1)
        Q = np.zeros(n)
        Q[0] = np.log(q0)

        for j in range(1, n):
            i = 2 * (j - 1)

            k1 = self.dth * mumax_superfine[i] if i < len(mumax_superfine) else 0
            k2 = self.dth * mumax_superfine[i + 1] if i + 1 < len(mumax_superfine) else k1
            k3 = k2
            k4 = self.dth * mumax_superfine[i + 2] if i + 2 < len(mumax_superfine) else k2

            Q[j] = Q[j - 1] + (1 / 6) * (k1 + 2 * k2 + 2 * k3 + k4)

        Q_interp = CubicSpline(tt_fine, Q)
        Q_superfine = Q_interp(t_superfine)

        y = np.zeros(n)
        y[0] = self.y0

        for j in range(1, n):
            i = 2 * (j - 1)

            alpha_i = 1 / (1 + np.exp(-Q_superfine[i])) if i < len(Q_superfine) else 0
            alpha_i1 = 1 / (1 + np.exp(-Q_superfine[i + 1])) if i + 1 < len(Q_superfine) else alpha_i
            alpha_i2 = 1 / (1 + np.exp(-Q_superfine[i + 2])) if i + 2 < len(Q_superfine) else alpha_i1

            capacity_factor = 1 - np.exp(y[j - 1] - self.ymax)

            k1 = self.dth * mumax_superfine[i] * alpha_i * capacity_factor if i < len(mumax_superfine) else 0

            capacity_factor_k2 = 1 - np.exp((y[j - 1] + k1 / 2) - self.ymax)
            k2 = self.dth * mumax_superfine[i + 1] * alpha_i1 * capacity_factor_k2 if i + 1 < len(mumax_superfine) else k1

            capacity_factor_k3 = 1 - np.exp((y[j - 1] + k2 / 2) - self.ymax)
            k3 = self.dth * mumax_superfine[i + 1] * alpha_i1 * capacity_factor_k3 if i + 1 < len(mumax_superfine) else k2

            capacity_factor_k4 = 1 - np.exp((y[j - 1] + k3) - self.ymax)
            k4 = self.dth * mumax_superfine[i + 2] * alpha_i2 * capacity_factor_k4 if i + 2 < len(mumax_superfine) else k3

            y[j] = y[j - 1] + (1 / 6) * (k1 + 2 * k2 + 2 * k3 + k4)

        return {
            'time': tt_fine,
            'temperature': TT_fine,
            'population': y,
            'physiological_state': Q,
            'time_coarse': time_hours_coarse,
            'temperature_coarse': temperatures_coarse,
            'model_id': self.model_id,
            'model_label': self.meta.get('label'),
            'bacteria': self.meta.get('bacteria'),
            'citation': self.meta.get('citation'),
            'population_label': self.meta.get(
                'population_label', 'Population (Log CFU/g)'
            ),
            'show_pseudomonas_experiment': bool(
                self.meta.get('show_pseudomonas_experiment')
            ),
        }
