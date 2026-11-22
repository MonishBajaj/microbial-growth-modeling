"""Checks that ready catalog coefficients behave as the papers and the old MATLAB match say.

Run from this directory: python test_model_catalog.py
It prints PASS/FAIL lines and exits non-zero if a check fails. It does not
talk to MEATER, ThermoWorks, or an Arduino.
"""

from __future__ import annotations

import math
import sys

import numpy as np

from corrected_microbial_growth_model import CorrectedMicrobialGrowthModel
from pmp_catalog import DEFAULT_MODEL_ID, MODELS, list_models_for_api, require_ready


def _approx(actual, expected, tol, label):
    ok = abs(actual - expected) <= tol
    status = 'PASS' if ok else 'FAIL'
    print(f'  [{status}] {label}: got {actual:.6g}, expected {expected:.6g} ± {tol}')
    return ok


def test_catalog_honesty():
    print('\n== Catalog honesty ==')
    ready = [mid for mid, e in MODELS.items() if e['status'] == 'ready']
    pending = [mid for mid, e in MODELS.items() if e['status'] != 'ready']
    print(f'  Ready models ({len(ready)}): {ready}')
    print(f'  Pending models: {len(pending)} (listed, not runnable)')
    api = list_models_for_api()
    assert api['default_model_id'] == DEFAULT_MODEL_ID
    entry, err = require_ready('listeria_growth_aerobic_broth_aw')
    assert err and entry is not None
    print('  [PASS] Pending broth model is blocked by require_ready')
    return True


def test_legacy_pseudomonas_regression():
    print('\n== Legacy Pseudomonas / MATLAB sample-data regression ==')
    model = CorrectedMicrobialGrowthModel()
    assert model.model_id == DEFAULT_MODEL_ID
    time_hours = np.arange(0, 51, 1)
    temperatures = 25 + 10 * np.sin(2 * np.pi * time_hours / 6)
    results = model.simulate_growth(time_hours, temperatures)
    final = float(results['population'][-1])
    # Sample profile saturates at ymax=8; lock to current integrator output.
    ok = _approx(final, 7.99999, 0.01, 'final population on sinusoidal sample data')
    ok = _approx(float(results['population'][0]), 2.51, 1e-9, 'y0') and ok
    overlay = results.get('show_pseudomonas_experiment') is True
    print(f'  [{"PASS" if overlay else "FAIL"}] experimental overlay flag on')
    return ok and overlay


def test_juneja_egr_table4():
    print('\n== Juneja 2001 C. perfringens EGR vs Table 4 predictions ==')
    model = CorrectedMicrobialGrowthModel.from_catalog(
        'clostridium_perfringens_cooling_juneja_2001'
    )
    # Predicted EGR column from Juneja Table 4 (not the noisy experimental means).
    checks = [
        (25.0, 0.42, 0.03),
        (37.0, 1.37, 0.05),
        (15.0, 0.05, 0.03),
        (50.0, 1.05, 0.15),
    ]
    ok = True
    for temp, expected, tol in checks:
        got = model.secondary_model(temp)
        ok = _approx(got, expected, tol, f'EGR at {temp} °C') and ok
    ok = _approx(model.secondary_model(5.0), 0.0, 0.0, 'EGR below Tmin') and ok
    ok = _approx(model.secondary_model(55.0), 0.0, 0.0, 'EGR above Tmax') and ok
    return ok


def test_juneja_botulinum_positive_midrange():
    print('\n== Juneja 2001 C. botulinum sanity ==')
    model = CorrectedMicrobialGrowthModel.from_catalog(
        'clostridium_botulinum_cooling_juneja_2001'
    )
    egr37 = model.secondary_model(37.0)
    # Table 4 predicted EGR at 37 °C ≈ 0.92
    ok = _approx(egr37, 0.92, 0.08, 'EGR at 37 °C')
    return ok


def test_test_parameter_bacillus():
    print('\n== Test_Parameter Bacillus cereus ==')
    entry, err = require_ready('Test_Parameter')
    ok = err is None and entry is not None
    print(f'  [{"PASS" if ok else "FAIL"}] Test_Parameter is a ready catalog model')
    if not ok:
        return False
    model = CorrectedMicrobialGrowthModel.from_catalog('Test_Parameter')
    ok = model.y0 == 0.0 and model.ymax == 8.0 and model.h0 == 3.04
    print(f'  [{"PASS" if ok else "FAIL"}] y0=0, ymax=8, h0=3.04')
    # μ = a*(T-Tmin)^2*(1-exp(b*(T-Tmax))) at 30 °C
    expected_30 = 0.0023 * (30.0 - 8.94) ** 2 * (1.0 - math.exp(0.0783 * (30.0 - 54.11)))
    ok = _approx(model.secondary_model(30.0), expected_30, 1e-9, 'EGR at 30 °C') and ok
    ok = _approx(model.secondary_model(8.94), 0.0, 0.0, 'EGR at Tmin') and ok
    ok = _approx(model.secondary_model(54.11), 0.0, 0.0, 'EGR at Tmax') and ok
    ok = _approx(model.secondary_model(5.0), 0.0, 0.0, 'EGR below Tmin') and ok
    time_hours = np.linspace(0, 10, 11)
    temperatures = np.full_like(time_hours, 30.0)
    results = model.simulate_growth(time_hours, temperatures)
    grew = float(results['population'][-1]) > float(results['population'][0])
    print(f'  [{"PASS" if grew else "FAIL"}] population increases at 30 °C')
    title_ok = results.get('model_label') == 'Test_Parameter'
    cite_ok = results.get('citation') == (
        'A dynamic predictive model for Bacillus cereus growth from spores '
        'under temperature abuse conditions'
    )
    print(f'  [{"PASS" if title_ok and cite_ok else "FAIL"}] label and citation text')
    return ok and grew and title_ok and cite_ok


def test_cooling_profiles_directionally():
    print('\n== Cooling profile directionality (C. perfringens) ==')
    model = CorrectedMicrobialGrowthModel.from_catalog(
        'clostridium_perfringens_cooling_juneja_2001'
    )

    # Juneja Table 1 style: 54.4 → 7.2 °C
    def profile(hours, points):
        t = np.linspace(0, hours, points)
        # Approximate exponential-ish cool from 54.4 to 7.2
        temps = 7.2 + (54.4 - 7.2) * np.exp(-3.0 * t / hours)
        return t, temps

    t15, T15 = profile(15, 61)
    t18, T18 = profile(18, 73)
    r15 = model.simulate_growth(t15, T15)
    r18 = model.simulate_growth(t18, T18)
    growth15 = float(r15['population'][-1] - r15['population'][0])
    growth18 = float(r18['population'][-1] - r18['population'][0])
    print(f'  growth Δlog over ~15 h cool: {growth15:.3f}')
    print(f'  growth Δlog over ~18 h cool: {growth18:.3f}')
    # Literature: 15 h “safe” (little/no outgrowth), 18 h hazardous. We only
    # assert the slower cool grows at least as much — not PMP bit-identity.
    ok = growth18 + 1e-9 >= growth15
    print(f'  [{"PASS" if ok else "FAIL"}] slower cool grows at least as much as faster cool')
    if growth15 > 1.5:
        print(
            '  [NOTE] 15 h cool still predicts >1.5 log growth with broth rates; '
            'Juneja meat “safe” result is matrix-specific — do not treat this as '
            'PMP meat validation.'
        )
    return ok


def main():
    results = [
        test_catalog_honesty(),
        test_legacy_pseudomonas_regression(),
        test_juneja_egr_table4(),
        test_juneja_botulinum_positive_midrange(),
        test_test_parameter_bacillus(),
        test_cooling_profiles_directionally(),
    ]
    print('\n== Summary ==')
    if all(results):
        print('All checks passed (within stated honesty limits).')
        return 0
    print('One or more checks FAILED.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
