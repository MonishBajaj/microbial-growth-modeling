"""Catalog of broth Growth and Cooling models for the dashboard.

Only entries with ``status == 'ready'`` carry coefficients we can defend.
PMP Online does not publish a parameter API; most broth Growth models use
response-surface polynomials that are not freely available as complete
coefficient tables here. Those stay listed but disabled until sourced.

Ready cooling rates for C. perfringens and C. botulinum use Juneja (2001)
Ratkowsky parameters (EGR in log10 CFU/h), which match the temperature-only
+ fixed-defaults rule and the Baranyi dynamic engine already in this project.
"""

from __future__ import annotations

from copy import deepcopy

# Default selectable model: MATLAB-matched Pseudomonas used by sample-data validation.
DEFAULT_MODEL_ID = 'pseudomonas_legacy_matlab'

# Juneja, V.K. 2001. Predictive Models for Growth of Foodborne Pathogenic
# Spore-Formers... 54th Reciprocal Meat Conference. Table 3 (logistic EGR).
# EGR = [a_g * (T - Tmin)]^2 * (1 - exp(b_g * (T - Tmax)))
# EGR units: log10(CFU/ml)/h — same log10 scale as this project's integrator.
_JUNEJA_CP_EGR = {
    'secondary': 'ratkowsky_sqrt_egr',
    'a': 0.044,
    'b': 0.419,
    'Tmin_C': 10.126,
    'Tmax_C': 51.020,
    # Representative h0 ≈ EGR*GOL near mid-range (Table 4, 37 °C): 1.37 * 3.56 ≈ 4.9
    'y0': 1.5,
    'ymax': 8.0,
    'h0': 4.88,
    'growth_floor_C': None,
}

_JUNEJA_CB_EGR = {
    'secondary': 'ratkowsky_sqrt_egr',
    'a': 0.033,
    'b': 0.167,
    'Tmin_C': 6.299,
    'Tmax_C': 50.012,
    # Table 4 ~37 °C: EGR≈0.92, GOL≈4.65 → h0≈4.3
    'y0': 1.5,
    'ymax': 8.0,
    'h0': 4.28,
    'growth_floor_C': None,
}

_PSEUDOMONAS = {
    'secondary': 'legacy_quadratic',
    'a': 0.0005,
    'b': 4.7509,
    'Tmin_C': -1.6081,
    'Tmax_C': 35.1581,
    'y0': 2.51,
    'ymax': 8.0,
    'h0': 1.07,
    'growth_floor_C': 15.0,
}

# Modified Ratkowsky, same expanded form as the legacy Pseudomonas secondary model:
#   μ = a * (T - Tmin)^2 * (1 - exp(b * (T - Tmax)))
# log10 CFU/h. h0 is the paper's average physiological state (not in the
# supplied coefficient list); the Baranyi integrator cannot run without it.
_TEST_PARAMETER = {
    'secondary': 'legacy_quadratic',
    'a': 0.0023,
    'b': 0.0783,
    'Tmin_C': 8.94,
    'Tmax_C': 54.11,
    'y0': 0.0,
    'ymax': 8.0,
    'h0': 3.04,
    'growth_floor_C': None,
}


def _pending(bacteria, family, label, pmp_path, reason, defaults=None):
    return {
        'bacteria': bacteria,
        'family': family,
        'label': label,
        'pmp_path': pmp_path,
        'status': 'pending_coefficients',
        'reason': reason,
        'defaults': defaults or {},
        'coeffs': None,
        'citation': None,
        'population_label': f'{bacteria} population (Log CFU/g)',
        'show_pseudomonas_experiment': False,
    }


MODELS = {
    DEFAULT_MODEL_ID: {
        'bacteria': 'Pseudomonas (project baseline)',
        'family': 'growth',
        'label': 'Legacy Baranyi + temperature (MATLAB-matched)',
        'pmp_path': None,
        'status': 'ready',
        'reason': (
            'Not a USDA PMP pathogen model. Kept because sample-data plots and '
            'experimental points in this repo were validated against these coefficients.'
        ),
        'defaults': {'note': 'Temperature-only secondary model; no pH/NaCl inputs.'},
        'coeffs': _PSEUDOMONAS,
        'citation': 'Project MATLAB reference implementation (see example_usage.py).',
        'population_label': 'Pseudomonas population (Log CFU/g)',
        'show_pseudomonas_experiment': True,
    },
    'clostridium_perfringens_cooling_juneja_2001': {
        'bacteria': 'Clostridium perfringens',
        'family': 'cooling',
        'label': 'Cooling — Juneja 2001 Ratkowsky EGR (broth rates, dynamic T)',
        'pmp_path': 'Cooling / Clostridium perfringens (related; not bit-identical to each PMP meat variant)',
        'status': 'ready',
        'reason': None,
        'defaults': {
            'matrix': 'TPGY broth rates applied to a measured cooling T(t)',
            'note': 'Food cure/salt is not modeled; use PMP meat-specific variants for that.',
        },
        'coeffs': _JUNEJA_CP_EGR,
        'citation': (
            'Juneja, V.K. (2001). Predictive Models for Growth of Foodborne Pathogenic '
            'Spore-Formers at Temperatures Applicable to Cooling of Cooked Meat. '
            '54th Reciprocal Meat Conference, Table 3 (a_g, b_g, Tmin, Tmax for EGR).'
        ),
        'population_label': 'C. perfringens population (Log CFU/g)',
        'show_pseudomonas_experiment': False,
    },
    'clostridium_botulinum_cooling_juneja_2001': {
        'bacteria': 'Clostridium botulinum',
        'family': 'cooling',
        'label': 'Cooling — Juneja 2001 Ratkowsky EGR (broth rates, dynamic T)',
        'pmp_path': 'Cooling / Clostridium botulinum (related; not bit-identical to each PMP meat variant)',
        'status': 'ready',
        'reason': None,
        'defaults': {
            'matrix': 'RCM broth rates applied to a measured cooling T(t)',
            'note': 'Meat-specific PMP cooling matrices are not encoded here.',
        },
        'coeffs': _JUNEJA_CB_EGR,
        'citation': (
            'Juneja, V.K. (2001). Predictive Models for Growth of Foodborne Pathogenic '
            'Spore-Formers at Temperatures Applicable to Cooling of Cooked Meat. '
            '54th Reciprocal Meat Conference, Table 3 (C. botulinum EGR parameters).'
        ),
        'population_label': 'C. botulinum population (Log CFU/g)',
        'show_pseudomonas_experiment': False,
    },
    'Test_Parameter': {
        'bacteria': 'Bacillus cereus',
        'family': 'growth',
        'label': 'Test_Parameter',
        'pmp_path': None,
        'status': 'ready',
        'reason': None,
        'defaults': {
            'matrix': 'Tryptic soy broth, growth from spores',
            'note': (
                'Tmin = 8.94 °C, Tmax = 54.11 °C, a = 0.0023, b = 0.0783, '
                'y0 = 0, ymax = 8. Lag uses the paper average h0 = 3.04.'
            ),
        },
        'coeffs': _TEST_PARAMETER,
        'citation': (
            'A dynamic predictive model for Bacillus cereus growth from spores '
            'under temperature abuse conditions'
        ),
        'population_label': 'Bacillus cereus population (Log CFU/g)',
        'show_pseudomonas_experiment': False,
    },
}

_BROTH_PENDING_REASON = (
    'USDA PMP broth Growth models use Gompertz response-surface polynomials in '
    'T, pH, NaCl (and often nitrite). Full coefficient tables are not available '
    'here without the source publications; enabling them with guessed numbers '
    'would be incorrect.'
)

_COOLING_PENDING_REASON = (
    'This PMP cooling variant is food-matrix specific. Verified Juneja 2001 '
    'temperature-only rates are available under the ready C. perfringens / '
    'C. botulinum cooling entries; matrix-specific PMP polynomials are not loaded.'
)

# Broth Growth (aerobic / anaerobic) — listed for UI, not runnable yet.
for _bid, _bact, _label, _path in [
    ('aeromonas_hydrophila_growth_aerobic_broth', 'Aeromonas hydrophila',
     'Growth Aerobic (Broth Culture)', 'Growth / Aerobic / Broth / Aeromonas hydrophila'),
    ('aeromonas_hydrophila_growth_anaerobic_broth', 'Aeromonas hydrophila',
     'Growth Anaerobic (Broth Culture)', 'Growth / Anaerobic / Broth / Aeromonas hydrophila'),
    ('bacillus_cereus_growth_aerobic_broth', 'Bacillus cereus',
     'Growth Aerobic (Broth Culture)', 'Growth / Aerobic / Broth / Bacillus cereus'),
    ('bacillus_cereus_growth_anaerobic_broth', 'Bacillus cereus',
     'Growth Anaerobic (Broth Culture)', 'Growth / Anaerobic / Broth / Bacillus cereus'),
    ('clostridium_perfringens_growth_anaerobic_broth', 'Clostridium perfringens',
     'Growth Anaerobic (Broth Culture)', 'Growth / Anaerobic / Broth / Clostridium perfringens'),
    ('ecoli_o157_growth_aerobic_broth', 'Escherichia coli [O157:H7]',
     'Growth Aerobic (Broth Culture)', 'Growth / Aerobic / Broth / Escherichia coli [O157:H7]'),
    ('listeria_growth_aerobic_broth_aw', 'Listeria monocytogenes',
     'Growth Aerobic (Broth Culture, aW)', 'Growth / Aerobic / Broth / Listeria monocytogenes (aW)'),
    ('listeria_growth_aerobic_broth_nacl', 'Listeria monocytogenes',
     'Growth Aerobic (Broth Culture, NaCl)', 'Growth / Aerobic / Broth / Listeria monocytogenes (NaCl)'),
    ('listeria_growth_anaerobic_broth_aw', 'Listeria monocytogenes',
     'Growth Anaerobic (Broth Culture, aW)', 'Growth / Anaerobic / Broth / Listeria monocytogenes (aW)'),
    ('listeria_growth_anaerobic_broth_nacl', 'Listeria monocytogenes',
     'Growth Anaerobic (Broth Culture, NaCl)', 'Growth / Anaerobic / Broth / Listeria monocytogenes (NaCl)'),
    ('salmonella_spp_growth_aerobic_broth', 'Salmonella spp.',
     'Growth Aerobic (Broth Culture)', 'Growth / Aerobic / Broth / Salmonella spp.'),
    ('shigella_flexneri_growth_aerobic_broth', 'Shigella flexneri',
     'Growth Aerobic (Broth Culture)', 'Growth / Aerobic / Broth / Shigella flexneri'),
    ('shigella_flexneri_growth_anaerobic_broth', 'Shigella flexneri',
     'Growth Anaerobic (Broth Culture)', 'Growth / Anaerobic / Broth / Shigella flexneri'),
    ('staphylococcus_aureus_growth_aerobic_broth', 'Staphylococcus aureus',
     'Growth Aerobic (Broth Culture)', 'Growth / Aerobic / Broth / Staphylococcus aureus'),
    ('staphylococcus_aureus_growth_anaerobic_broth', 'Staphylococcus aureus',
     'Growth Anaerobic (Broth Culture)', 'Growth / Anaerobic / Broth / Staphylococcus aureus'),
    ('yersinia_enterocolitica_growth_aerobic_broth', 'Yersinia enterocolitica',
     'Growth Aerobic (Broth)', 'Growth / Aerobic / Broth / Yersinia enterocolitica'),
]:
    MODELS[_bid] = _pending(
        _bact, 'growth', _label, _path, _BROTH_PENDING_REASON,
        defaults={'pH': 'fixed when coefficients are added', 'NaCl_or_aW': 'fixed when coefficients are added'},
    )

# Cooling variants — listed; use ready Juneja entries for runnable cooling.
for _bid, _bact, _label, _path in [
    ('bacillus_cereus_cooling_beans', 'Bacillus cereus', 'Cooling in Cooked Beans',
     'Cooling / Bacillus cereus in Cooked Beans'),
    ('bacillus_cereus_cooling_pasta', 'Bacillus cereus', 'Cooling in Cooked Pasta',
     'Cooling / Bacillus cereus in Cooked Pasta'),
    ('bacillus_cereus_cooling_rice', 'Bacillus cereus', 'Cooling in Cooked Rice',
     'Cooling / Bacillus cereus in Cooked Rice'),
    ('clostridium_botulinum_cooling_broth', 'Clostridium botulinum', 'Cooling (broth culture)',
     'Cooling / Clostridium botulinum (broth culture)'),
    ('clostridium_botulinum_cooling_beef', 'Clostridium botulinum',
     'Cooling in cooked uncured ground beef', 'Cooling / Clostridium botulinum in beef'),
    ('clostridium_botulinum_cooling_chicken', 'Clostridium botulinum',
     'Cooling in cooked ground chicken', 'Cooling / Clostridium botulinum in chicken'),
    ('clostridium_botulinum_cooling_pork', 'Clostridium botulinum',
     'Cooling in cooked ground pork', 'Cooling / Clostridium botulinum in pork'),
    ('clostridium_perfringens_cooling_beef_cooked', 'Clostridium perfringens',
     'Cooling in cooked beef', 'Cooling / Clostridium perfringens in beef (cooked)'),
    ('clostridium_perfringens_cooling_beef_uncured', 'Clostridium perfringens',
     'Cooling of cooked beef (uncured)', 'Cooling / Clostridium perfringens in beef (cooked, uncured)'),
    ('clostridium_perfringens_cooling_beef_cured', 'Clostridium perfringens',
     'Cooling of cooked beef (cured)', 'Cooling / Clostridium perfringens in beef (cured)'),
    ('clostridium_perfringens_cooling_chicken_uncured', 'Clostridium perfringens',
     'Cooling in cooked chicken (uncured)', 'Cooling / Clostridium perfringens in chicken (uncured)'),
    ('clostridium_perfringens_cooling_chicken_cured', 'Clostridium perfringens',
     'Cooling of cooked chicken (cured)', 'Cooling / Clostridium perfringens in chicken (cured)'),
    ('clostridium_perfringens_cooling_pork_cured', 'Clostridium perfringens',
     'Cooling in cooked pork (cured)', 'Cooling / Clostridium perfringens in pork (cured)'),
    ('clostridium_perfringens_cooling_pork_uncured', 'Clostridium perfringens',
     'Cooling in cooked pork (uncured)', 'Cooling / Clostridium perfringens in pork (uncured)'),
    ('clostridium_perfringens_cooling_pork_salt_phosphate', 'Clostridium perfringens',
     'Cooling in cooked pork (salt, phosphate)',
     'Cooling / Clostridium perfringens in pork (salt, phosphate)'),
]:
    MODELS[_bid] = _pending(_bact, 'cooling', _label, _path, _COOLING_PENDING_REASON)


def get_model(model_id):
    """Return a deep copy of a catalog entry, or None."""
    entry = MODELS.get(model_id)
    return deepcopy(entry) if entry else None


def list_models_for_api():
    """JSON-friendly catalog for the dashboard Bacteria → Model pickers."""
    bacteria = {}
    for model_id, entry in MODELS.items():
        bact = entry['bacteria']
        bacteria.setdefault(bact, [])
        bacteria[bact].append({
            'id': model_id,
            'label': entry['label'],
            'family': entry['family'],
            'status': entry['status'],
            'ready': entry['status'] == 'ready',
            'reason': entry.get('reason'),
            'defaults': entry.get('defaults') or {},
            'citation': entry.get('citation'),
            'pmp_path': entry.get('pmp_path'),
        })
    for models in bacteria.values():
        models.sort(key=lambda m: (0 if m['ready'] else 1, m['label']))
    return {
        'default_model_id': DEFAULT_MODEL_ID,
        'bacteria': sorted(bacteria.keys()),
        'models_by_bacteria': bacteria,
    }


def require_ready(model_id):
    """Return (entry, error_message). error_message is None when ready."""
    entry = get_model(model_id)
    if entry is None:
        return None, f'Unknown model id: {model_id}'
    if entry['status'] != 'ready' or not entry.get('coeffs'):
        reason = entry.get('reason') or 'Coefficients are not available yet.'
        return entry, reason
    return entry, None
