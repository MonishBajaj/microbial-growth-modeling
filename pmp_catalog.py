"""Catalog of growth and cooling models the dashboard can offer.

Only status == 'ready' entries have coefficients the integrator is allowed to
use. The other entries exist so the Bacteria and Food menus match USDA PMP
Online names, and they stay disabled. require_ready() is what app.py calls
before a short, full, or sample run.

Ready sets today: the project Pseudomonas baseline, Juneja 2001 cooling rates
for C. perfringens and C. botulinum, and the Bacillus cereus Test_Parameter set.
Adding a model means a new MODELS entry with coeffs the secondary model
understands (legacy_quadratic or ratkowsky_sqrt_egr).

PMP Online does not publish a parameter API. Most of its models are
response-surface polynomials, and this file does not include those full
tables. Food names still follow the USDA PMP Online Bacteria, then Model,
submenu (https://pmp.ars.usda.gov/PMPOnline.aspx). The ready cooling rates
use Juneja (2001) Ratkowsky parameters, with EGR in log10 CFU/h, on the same
temperature-only Baranyi integrator as the rest of the project.
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


def _pending(bacteria, family, label, food, pmp_path, reason, defaults=None):
    return {
        'bacteria': bacteria,
        'family': family,
        'label': label,
        'food': food,
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
        'food': 'Project baseline (temperature-only; not a PMP food)',
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
        'food': 'Broth culture (Juneja 2001 rates, dynamic T)',
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
        'food': 'Cooling (broth culture) — Juneja 2001 rates',
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
        'food': 'Growth from spores (dynamic temperature; project paper)',
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

_OTHER_PENDING_REASON = (
    'Listed from USDA PMP Online. Coefficients for this food/process variant '
    'are not loaded yet; the entry stays unavailable until a verified source is added.'
)

# --- Pending entries: food text matches PMP Online Bacteria → Model submenu ---

# Aeromonas hydrophila
for _bid, _food, _family, _path in [
    ('aeromonas_hydrophila_growth_aerobic_broth',
     'Growth Aerobic (Broth Culture)', 'growth',
     'Growth / Aerobic / Broth / Aeromonas hydrophila'),
    ('aeromonas_hydrophila_growth_anaerobic_broth',
     'Growth Anaerobic (Broth Culture)', 'growth',
     'Growth / Anaerobic / Broth / Aeromonas hydrophila'),
]:
    MODELS[_bid] = _pending(
        'Aeromonas hydrophila', _family, _food, _food, _path, _BROTH_PENDING_REASON,
        defaults={'pH': 'fixed when coefficients are added', 'NaCl_or_aW': 'fixed when coefficients are added'},
    )

# Bacillus cereus
for _bid, _food, _family, _path, _reason in [
    ('bacillus_cereus_cooling_beans', 'Cooling in Cooked Beans', 'cooling',
     'Cooling / Bacillus cereus in Cooked Beans', _COOLING_PENDING_REASON),
    ('bacillus_cereus_cooling_pasta', 'Cooling in Cooked Pasta', 'cooling',
     'Cooling / Bacillus cereus in Cooked Pasta', _COOLING_PENDING_REASON),
    ('bacillus_cereus_cooling_rice', 'Cooling in Cooked Rice', 'cooling',
     'Cooling / Bacillus cereus in Cooked Rice', _COOLING_PENDING_REASON),
    ('bacillus_cereus_growth_aerobic_broth', 'Growth Aerobic (Broth Culture)', 'growth',
     'Growth / Aerobic / Broth / Bacillus cereus', _BROTH_PENDING_REASON),
    ('bacillus_cereus_growth_anaerobic_broth', 'Growth Anaerobic (Broth Culture)', 'growth',
     'Growth / Anaerobic / Broth / Bacillus cereus', _BROTH_PENDING_REASON),
    ('bacillus_cereus_thermal_rice', 'Thermal Inactivation in Cooked Rice', 'heat_inactivation',
     'Heat Inactivation / Bacillus cereus in Cooked Rice', _OTHER_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        'Bacillus cereus', _family, _food, _food, _path, _reason,
        defaults={'pH': 'fixed when coefficients are added'} if _family == 'growth' else {},
    )

# Clostridium botulinum
for _bid, _food, _path in [
    ('clostridium_botulinum_cooling_broth', 'Cooling (broth culture)',
     'Cooling / Clostridium botulinum (broth culture)'),
    ('clostridium_botulinum_cooling_chicken', 'Cooling in cooked ground chicken',
     'Cooling / Clostridium botulinum in chicken'),
    ('clostridium_botulinum_cooling_pork', 'Cooling in cooked ground pork',
     'Cooling / Clostridium botulinum in pork'),
    ('clostridium_botulinum_cooling_beef', 'Cooling in cooked uncured ground beef',
     'Cooling / Clostridium botulinum in beef'),
]:
    MODELS[_bid] = _pending(
        'Clostridium botulinum', 'cooling', _food, _food, _path, _COOLING_PENDING_REASON,
    )

# Clostridium perfringens
for _bid, _food, _family, _path, _reason in [
    ('clostridium_perfringens_cooling_beef_cooked', 'Cooling in cooked beef', 'cooling',
     'Cooling / Clostridium perfringens in beef (cooked)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_beef_uncured', 'Cooling of cooked beef (uncured)', 'cooling',
     'Cooling / Clostridium perfringens in beef (cooked, uncured)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_beef_cured', 'Cooling of cooked beef (cured)', 'cooling',
     'Cooling / Clostridium perfringens in beef (cured)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_chicken_cured', 'Cooling of cooked chicken (cured)', 'cooling',
     'Cooling / Clostridium perfringens in chicken (cured)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_chicken_uncured', 'Cooling in cooked chicken (uncured)', 'cooling',
     'Cooling / Clostridium perfringens in chicken (uncured)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_pork_cured', 'Cooling in cooked pork (cured)', 'cooling',
     'Cooling / Clostridium perfringens in pork (cured)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_pork_uncured', 'Cooling in cooked pork (uncured)', 'cooling',
     'Cooling / Clostridium perfringens in pork (uncured)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_cooling_pork_salt_phosphate',
     'Cooling in cooked pork (salt, phosphate)', 'cooling',
     'Cooling / Clostridium perfringens in pork (salt, phosphate)', _COOLING_PENDING_REASON),
    ('clostridium_perfringens_growth_anaerobic_broth', 'Growth Anaerobic (Broth Culture)', 'growth',
     'Growth / Anaerobic / Broth / Clostridium perfringens', _BROTH_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        'Clostridium perfringens', _family, _food, _food, _path, _reason,
        defaults={'pH': 'fixed when coefficients are added'} if _family == 'growth' else {},
    )

# Escherichia coli [O104:H4]
MODELS['ecoli_o104_growth_sprouts'] = _pending(
    'Escherichia coli [O104:H4]', 'growth',
    'Growth Aerobic (Sprouts)', 'Growth Aerobic (Sprouts)',
    'Growth / Aerobic / Sprouts / Escherichia coli [O104:H4]',
    _OTHER_PENDING_REASON,
)

# Escherichia coli [O157:H7]
for _bid, _food, _family, _path, _reason in [
    ('ecoli_o157_growth_aerobic_broth', 'Growth Aerobic (Broth Culture)', 'growth',
     'Growth / Aerobic / Broth / Escherichia coli [O157:H7]', _BROTH_PENDING_REASON),
    ('ecoli_o157_heat_ground_beef_ph_nacl_spp',
     'Heat Inactivation (Ground Beef: pH, NaCL, SPP)', 'heat_inactivation',
     'Heat Inactivation / Escherichia coli [O157:H7] (Ground Beef: pH, NaCL, SPP)',
     _OTHER_PENDING_REASON),
    ('ecoli_o157_heat_ground_beef_tea_apple',
     'Heat Inactivation (Ground Beef: Tea Leaf and Apple Skin Powders)', 'heat_inactivation',
     'Heat Inactivation / Escherichia coli (Ground Beef: Tea Leaf and Apple Skin Powders)',
     _OTHER_PENDING_REASON),
    ('ecoli_o157_survival', 'Survival', 'survival',
     'Survival / Escherichia coli [O157:H7]', _OTHER_PENDING_REASON),
    ('ecoli_o157_survival_cooked_ham', 'Survival (Cooked Ham)', 'survival',
     'Survival / Escherichia coli [O157:H7] (Cooked Ham)', _OTHER_PENDING_REASON),
    ('ecoli_o157_survival_fermented_sausage_fermentation',
     'Survival (Fermented Sausage, Fermentation)', 'survival',
     'Survival / Escherichia coli [O157:H7] (Fermented Sausage, Fermentation)',
     _OTHER_PENDING_REASON),
    ('ecoli_o157_survival_fermented_sausage_drying',
     'Survival (Fermented Sausage, Drying)', 'survival',
     'Survival / Escherichia coli [O157:H7] (Fermented Sausage, Drying)',
     _OTHER_PENDING_REASON),
    ('ecoli_o157_survival_fermented_sausage_storage',
     'Survival (Fermented Sausage, Storage)', 'survival',
     'Survival / Escherichia coli [O157:H7] (Fermented Sausage, Storage)',
     _OTHER_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        'Escherichia coli [O157:H7]', _family, _food, _food, _path, _reason,
        defaults={'pH': 'fixed when coefficients are added'} if _family == 'growth' else {},
    )

# Listeria monocytogenes
for _bid, _food, _family, _path, _reason in [
    ('listeria_growth_aerobic_broth_aw', 'Growth Aerobic (Broth Culture, aW)', 'growth',
     'Growth / Aerobic / Broth / Listeria monocytogenes (aW)', _BROTH_PENDING_REASON),
    ('listeria_growth_aerobic_broth_nacl', 'Growth Aerobic (Broth Culture, NaCl)', 'growth',
     'Growth / Aerobic / Broth / Listeria monocytogenes (NaCl)', _BROTH_PENDING_REASON),
    ('listeria_growth_anaerobic_broth_aw', 'Growth Anaerobic (Broth Culture, aW)', 'growth',
     'Growth / Anaerobic / Broth / Listeria monocytogenes (aW)', _BROTH_PENDING_REASON),
    ('listeria_growth_anaerobic_broth_nacl', 'Growth Anaerobic (Broth Culture, NaCl)', 'growth',
     'Growth / Anaerobic / Broth / Listeria monocytogenes (NaCl)', _BROTH_PENDING_REASON),
    ('listeria_growth_aerobic_ground_ham', 'Growth Aerobic (Ground Ham)', 'growth',
     'Growth / Aerobic / Ground Ham / Listeria monocytogenes', _OTHER_PENDING_REASON),
    ('listeria_growth_aerobic_shrimp_crab_salad',
     'Growth Aerobic (Shrimp and Imitation Crab Salad)', 'growth',
     'Growth / Aerobic / Shrimp and Imitation Crab Salad / Listeria monocytogenes',
     _OTHER_PENDING_REASON),
    ('listeria_growth_aerobic_smoked_salmon', 'Growth Aerobic (Smoked Salmon)', 'growth',
     'Growth / Aerobic / Smoked Salmon / Listeria monocytogenes', _OTHER_PENDING_REASON),
    ('listeria_growth_anaerobic_shrimp_crab_salad',
     'Growth Anaerobic (Shrimp and Imitation Crab Salad)', 'growth',
     'Growth / Anaerobic / Shrimp and Imitation Crab Salad / Listeria monocytogenes',
     _OTHER_PENDING_REASON),
    ('listeria_growth_anaerobic_ground_ham', 'Growth Anaerobic (Ground Ham)', 'growth',
     'Growth / Anaerobic / Ground Ham / Listeria monocytogenes', _OTHER_PENDING_REASON),
    ('listeria_heat_ground_beef_apple_polyphenols',
     'Heat Inactivation (Ground Beef - NaCL, Apple Polyphenols)', 'heat_inactivation',
     'Heat Inactivation / Listeria monocytogenes (Ground Beef - NaCL, Apple Polyphenols)',
     _OTHER_PENDING_REASON),
    ('listeria_heat_ground_beef_nacl_spp_lactate',
     'Heat Inactivation (Ground Beef - NaCl, Sodium Pyrophosphate, and Sodium Lactate)',
     'heat_inactivation',
     'Heat Inactivation / Listeria monocytogenes (Ground Beef - NaCl, SPP, Sodium Lactate)',
     _OTHER_PENDING_REASON),
    ('listeria_heat_ground_beef_lactate_diacetate',
     'Heat Inactivation (Ground Beef - Sodium Lactate and Sodium Diacetate)',
     'heat_inactivation',
     'Heat Inactivation / Listeria monocytogenes (Ground Beef - Lactate / Diacetate)',
     _OTHER_PENDING_REASON),
    ('listeria_heat_ground_beef_sous_vide',
     'Heat Inactivation (Ground Beef - Sous-vide)', 'heat_inactivation',
     'Heat Inactivation / Listeria monocytogenes (Ground Beef - Sous-vide)',
     _OTHER_PENDING_REASON),
    ('listeria_heat_simulated_beef_gravy',
     'Heat Inactivation (Simulated Beef Gravy)', 'heat_inactivation',
     'Heat Inactivation / Listeria monocytogenes (Simulated Beef Gravy)',
     _OTHER_PENDING_REASON),
    ('listeria_heat_turkey', 'Heat Inactivation (Turkey)', 'heat_inactivation',
     'Heat Inactivation / Listeria monocytogenes (Turkey)', _OTHER_PENDING_REASON),
    ('listeria_survival', 'Survival', 'survival',
     'Survival / Listeria monocytogenes', _OTHER_PENDING_REASON),
    ('listeria_survival_cooked_ham', 'Survival (Cooked Ham)', 'survival',
     'Survival / Listeria monocytogenes (Cooked Ham)', _OTHER_PENDING_REASON),
    ('listeria_survival_fermented_sausage_fermentation',
     'Survival (Fermented Sausage, Fermentation)', 'survival',
     'Survival / Listeria monocytogenes (Fermented Sausage, Fermentation)',
     _OTHER_PENDING_REASON),
    ('listeria_survival_fermented_sausage_drying',
     'Survival (Fermented Sausage, Drying)', 'survival',
     'Survival / Listeria monocytogenes (Fermented Sausage, Drying)',
     _OTHER_PENDING_REASON),
    ('listeria_survival_fermented_sausage_storage',
     'Survival (Fermented Sausage, Storage)', 'survival',
     'Survival / Listeria monocytogenes (Fermented Sausage, Storage)',
     _OTHER_PENDING_REASON),
    ('listeria_survival_salmon_smoking', 'Survival (Salmon, Smoking)', 'survival',
     'Survival / Listeria monocytogenes (Salmon, Smoking)', _OTHER_PENDING_REASON),
    ('listeria_transfer_salmon_slicing', 'Transfer (Salmon Slicing)', 'transfer',
     'Transfer / Listeria monocytogenes during slicing of salmon', _OTHER_PENDING_REASON),
    ('listeria_transfer_deli_meat_slicing', 'Transfer (Deli Meat Slicing)', 'transfer',
     'Transfer / Listeria monocytogenes during slicing of deli meat', _OTHER_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        'Listeria monocytogenes', _family, _food, _food, _path, _reason,
        defaults={'pH': 'fixed when coefficients are added'} if _family == 'growth' else {},
    )

# Salmonella dublin / enteritidis / hadar / kentucky
MODELS['salmonella_dublin_growth_chicken_burgers'] = _pending(
    'Salmonella dublin', 'growth',
    'Growth (Sterile Ground Chicken Burgers)', 'Growth (Sterile Ground Chicken Burgers)',
    'Growth / Salmonella Dublin in Sterile Ground Chicken Burgers', _OTHER_PENDING_REASON,
)
MODELS['salmonella_enteritidis_growth_chicken_burgers'] = _pending(
    'Salmonella enteritidis', 'growth',
    'Growth (Sterile Ground Chicken Burgers)', 'Growth (Sterile Ground Chicken Burgers)',
    'Growth / Salmonella Enteritidis in Sterile Ground Chicken Burgers', _OTHER_PENDING_REASON,
)
MODELS['salmonella_hadar_growth_chicken_skin'] = _pending(
    'Salmonella hadar', 'growth',
    'Growth Aerobic (Chicken Skin)', 'Growth Aerobic (Chicken Skin)',
    'Growth / Salmonella Hadar on Chicken Skin', _OTHER_PENDING_REASON,
)
MODELS['salmonella_kentucky_growth_chicken_skin'] = _pending(
    'Salmonella kentucky', 'growth',
    'Growth Aerobic (Chicken Skin)', 'Growth Aerobic (Chicken Skin)',
    'Growth / Salmonella Kentucky on Chicken Skin', _OTHER_PENDING_REASON,
)

# Salmonella typhimurium
for _bid, _food, _family, _path, _reason in [
    ('salmonella_typhimurium_growth_chicken_portions',
     'Growth (Sterile Ground Chicken Portions)', 'growth',
     'Growth / Salmonella Typhimurium in Sterile Ground Chicken Portions', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_chicken_burgers',
     'Growth (Sterile Ground Chicken Burgers)', 'growth',
     'Growth / Salmonella Typhimurium in Sterile Ground Chicken Burgers', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_broth_prev_ph',
     'Growth Aerobic (Broth Culture, Previous growth pH)', 'growth',
     'Growth / Aerobic / Broth / Salmonella typhimurium (Previous growth pH)', _BROTH_PENDING_REASON),
    ('salmonella_typhimurium_growth_ground_chicken',
     'Growth Aerobic (Ground Chicken)', 'growth',
     'Growth / Salmonella Typhimurium in Ground Chicken', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_chicken_frankfurters',
     'Growth Aerobic (Chicken Frankfurters)', 'growth',
     'Growth / Salmonella Typhimurium in Chicken Frankfurters', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_chicken_skin_regression',
     'Growth Aerobic (Chicken Skin, Regression)', 'growth',
     'Growth / Salmonella Typhimurium on Chicken Skin (Regression)', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_chicken_skin_nn',
     'Growth Aerobic (Chicken Skin, Neural Network)', 'growth',
     'Growth / Salmonella Typhimurium on Chicken Skin (Neural Network)', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_sterile_chicken_prev_nacl',
     'Growth Aerobic Sterile Chicken (Previous NaCl)', 'growth',
     'Growth / Salmonella typhimurium in Sterile Chicken (Previous NaCl)', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_sterile_chicken_prev_temp',
     'Growth Aerobic Sterile Chicken (Previous Temp)', 'growth',
     'Growth / Salmonella typhimurium in Sterile Chicken (Previous Temp)', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_growth_refrigerated_chicken_skin',
     'Growth Refrigerated (Chicken Skin)', 'growth',
     'Growth / Salmonella Typhimurium on Refrigerated Chicken Skin', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_survival_fermented_sausage_fermentation',
     'Survival (Fermented Sausage, Fermentation)', 'survival',
     'Survival / Salmonella Typhimurium (Fermented Sausage, Fermentation)', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_survival_fermented_sausage_drying',
     'Survival (Fermented Sausage, Drying)', 'survival',
     'Survival / Salmonella Typhimurium (Fermented Sausage, Drying)', _OTHER_PENDING_REASON),
    ('salmonella_typhimurium_survival_fermented_sausage_storage',
     'Survival (Fermented Sausage, Storage)', 'survival',
     'Survival / Salmonella Typhimurium (Fermented Sausage, Storage)', _OTHER_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        'Salmonella typhimurium', _family, _food, _food, _path, _reason,
    )

# Salmonella spp.
for _bid, _food, _family, _path, _reason in [
    ('salmonella_spp_growth_aerobic_broth', 'Growth Aerobic (Broth Culture)', 'growth',
     'Growth / Aerobic / Broth / Salmonella spp.', _BROTH_PENDING_REASON),
    ('salmonella_spp_growth_ground_beef', 'Growth Aerobic (Ground Beef)', 'growth',
     'Growth / Salmonella spp. in Ground Beef', _OTHER_PENDING_REASON),
    ('salmonella_spp_growth_ground_chicken', 'Growth Aerobic (Ground Chicken)', 'growth',
     'Growth / Salmonella spp. in Ground Chicken', _OTHER_PENDING_REASON),
    ('salmonella_spp_heat_ground_beef', 'Heat Inactivation (Ground Beef)', 'heat_inactivation',
     'Heat Inactivation / Salmonella Serotypes (Ground Beef)', _OTHER_PENDING_REASON),
    ('salmonella_spp_heat_ground_chicken', 'Heat Inactivation (Ground Chicken)', 'heat_inactivation',
     'Heat Inactivation / Salmonella Serotypes (Ground Chicken)', _OTHER_PENDING_REASON),
    ('salmonella_spp_heat_ground_chicken_cinnamaldehyde',
     'Heat Inactivation (Ground Chicken - trans-Cinnamaldehyde and Carvacrol)',
     'heat_inactivation',
     'Heat Inactivation / Salmonella Serotypes (Ground Chicken - Cinnamaldehyde / Carvacrol)',
     _OTHER_PENDING_REASON),
    ('salmonella_spp_heat_meat_jerky', 'Heat Inactivation (Meat Jerky)', 'heat_inactivation',
     'Heat Inactivation / Salmonella Spp. (Meat Jerky)', _OTHER_PENDING_REASON),
    ('salmonella_spp_survival', 'Survival', 'survival',
     'Survival / Salmonella spp.', _OTHER_PENDING_REASON),
    ('salmonella_spp_survival_cooked_ham', 'Survival (Cooked Ham)', 'survival',
     'Survival / Salmonella spp. (Cooked Ham)', _OTHER_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        'Salmonella spp.', _family, _food, _food, _path, _reason,
        defaults={'pH': 'fixed when coefficients are added'} if _family == 'growth' else {},
    )

# Shigella / Staphylococcus / Yersinia
for _bid, _bact, _food, _family, _path, _reason in [
    ('shigella_flexneri_growth_aerobic_broth', 'Shigella flexneri',
     'Growth Aerobic (Broth Culture)', 'growth',
     'Growth / Aerobic / Broth / Shigella flexneri', _BROTH_PENDING_REASON),
    ('shigella_flexneri_growth_anaerobic_broth', 'Shigella flexneri',
     'Growth Anaerobic (Broth Culture)', 'growth',
     'Growth / Anaerobic / Broth / Shigella flexneri', _BROTH_PENDING_REASON),
    ('staphylococcus_aureus_growth_aerobic_broth', 'Staphylococcus aureus',
     'Growth Aerobic (Broth Culture)', 'growth',
     'Growth / Aerobic / Broth / Staphylococcus aureus', _BROTH_PENDING_REASON),
    ('staphylococcus_aureus_growth_anaerobic_broth', 'Staphylococcus aureus',
     'Growth Anaerobic (Broth Culture)', 'growth',
     'Growth / Anaerobic / Broth / Staphylococcus aureus', _BROTH_PENDING_REASON),
    ('yersinia_pseudotuberculosis_growth_ground_beef', 'Yersinia pseudotuberculosis',
     'Growth Aerobic (Ground Beef)', 'growth',
     'Growth / Yersinia pseudotuberculosis in Ground Beef', _OTHER_PENDING_REASON),
    ('yersinia_enterocolitica_growth_aerobic_broth', 'Yersinia enterocolitica',
     'Growth Aerobic (Broth)', 'growth',
     'Growth / Aerobic / Broth / Yersinia enterocolitica', _BROTH_PENDING_REASON),
]:
    MODELS[_bid] = _pending(
        _bact, _family, _food, _food, _path, _reason,
        defaults={'pH': 'fixed when coefficients are added'} if _family == 'growth' else {},
    )


def get_model(model_id):
    """Return a deep copy of a catalog entry, or None."""
    entry = MODELS.get(model_id)
    return deepcopy(entry) if entry else None


def list_models_for_api():
    """JSON-friendly catalog for the dashboard Bacteria → Food pickers."""
    bacteria = {}
    for model_id, entry in MODELS.items():
        bact = entry['bacteria']
        bacteria.setdefault(bact, [])
        bacteria[bact].append({
            'id': model_id,
            'label': entry['label'],
            'food': entry.get('food') or entry['label'],
            'family': entry['family'],
            'status': entry['status'],
            'ready': entry['status'] == 'ready',
            'reason': entry.get('reason'),
            'defaults': entry.get('defaults') or {},
            'citation': entry.get('citation'),
            'pmp_path': entry.get('pmp_path'),
        })
    for models in bacteria.values():
        models.sort(key=lambda m: (0 if m['ready'] else 1, m['food'].lower()))
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
