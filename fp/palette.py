"""FormulaPilot Palette & Composition validation module (§8.1.1, §8.1.4)"""
import os
import csv
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Tuple, Optional

# Non-AQUA ingredients in exact order of ingredients.csv
INGREDIENTS = [
    "GLYCERIN",
    "NIACINAMIDE",
    "CETEARYL_ALCOHOL",
    "EMULSIFIER",
    "CCT",
    "DIMETHICONE",
    "XANTHAN",
    "CARBOMER",
    "NAOH",
    "PHENOXYETHANOL",
]

# Process parameters
PROCESS = ["RPM", "HMIN", "TEMP"]

# 14 Features in fixed order (§8.1.1)
FEATURES = INGREDIENTS + PROCESS + ["OIL_PHASE"]

DEFAULT_ASSUMPTIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "assumptions"
)


def load_palette(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Load ingredients.csv into a pandas DataFrame."""
    if csv_path is None:
        csv_path = os.path.join(DEFAULT_ASSUMPTIONS_DIR, "ingredients.csv")
    df = pd.read_csv(csv_path)
    return df


def bounds(csv_path: Optional[str] = None) -> Dict[str, Tuple[float, float]]:
    """Return min and max bounds for all ingredients and process parameters."""
    df = load_palette(csv_path)
    b = {}
    for _, row in df.iterrows():
        code = row["code"]
        b[code] = (float(row["min_pct"]), float(row["max_pct"]))
    
    # Process bounds (§8.1.1)
    b["RPM"] = (2000.0, 10000.0)
    b["HMIN"] = (1.0, 10.0)
    b["TEMP"] = (60.0, 85.0)
    return b


def complete(formula: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given ingredient and process dict, compute:
    AQUA = 100 - sum(non-AQUA ingredients)
    OIL_PHASE = CCT + DIMETHICONE + 0.5 * CETEARYL_ALCOHOL
    """
    f = dict(formula)
    non_water_sum = sum(float(f.get(code, 0.0)) for code in INGREDIENTS)
    aqua = 100.0 - non_water_sum
    f["AQUA"] = round(aqua, 6)
    
    cct = float(f.get("CCT", 0.0))
    dimethicone = float(f.get("DIMETHICONE", 0.0))
    cetearyl = float(f.get("CETEARYL_ALCOHOL", 0.0))
    f["OIL_PHASE"] = round(cct + dimethicone + 0.5 * cetearyl, 6)
    return f


def validate(formula: Dict[str, Any], b_dict: Optional[Dict[str, Tuple[float, float]]] = None) -> List[str]:
    """
    Validate a formula.
    Returns empty list if valid, or list of violation messages if invalid.
    Rules:
    - All ingredients and process parameters within bounds
    - AQUA >= 50
    - Total composition == 100 +- 0.001
    """
    if b_dict is None:
        b_dict = bounds()
    
    f = complete(formula)
    violations = []
    
    # Check bounds
    for k in INGREDIENTS + PROCESS:
        val = float(f.get(k, 0.0))
        lo, hi = b_dict.get(k, (0.0, 100.0))
        if val < lo - 1e-6 or val > hi + 1e-6:
            violations.append(f"{k} ({val}) out of bounds [{lo}, {hi}]")
            
    aqua_val = float(f.get("AQUA", 0.0))
    if aqua_val < 50.0 - 1e-6:
        violations.append(f"AQUA ({aqua_val}) below minimum 50%")
        
    total = sum(float(f.get(code, 0.0)) for code in INGREDIENTS) + aqua_val
    if abs(total - 100.0) > 1e-3:
        violations.append(f"Total percentage ({total}) != 100")
        
    return violations


def cost_idr_per_kg(formula: Dict[str, Any], csv_path: Optional[str] = None) -> float:
    """Calculate raw material cost per kg including AQUA (deterministic assumption)."""
    df = load_palette(csv_path)
    prices = dict(zip(df["code"], df["price_idr_per_kg"].astype(float)))
    f = complete(formula)
    
    total_cost = 0.0
    for code in INGREDIENTS + ["AQUA"]:
        pct = float(f.get(code, 0.0))
        price = prices.get(code, 0.0)
        total_cost += (pct / 100.0) * price
    return round(total_cost, 2)


def meets_specs(formula: Dict[str, Any], outputs: Dict[str, Any], specs: Dict[str, Any]) -> Dict[str, bool]:
    """
    Shared evaluation function (§8.1.5).
    Checks NIACINAMIDE_MIN_PCT, VISCOSITY_CP, PH, D50_UM_MAX, STABLE, COST_IDR_PER_KG_MAX, and ALL.
    """
    f = complete(formula)
    res = {}
    
    # NIACINAMIDE
    min_nia = specs.get("NIACINAMIDE_MIN_PCT", 0.0)
    res["NIACINAMIDE_MIN_PCT"] = float(f.get("NIACINAMIDE", 0.0)) >= (min_nia - 1e-6)
    
    # VISCOSITY_CP [min, max]
    visc_spec = specs.get("VISCOSITY_CP")
    if visc_spec is not None:
        vmin, vmax = visc_spec
        visc = float(outputs.get("VISCOSITY_CP", 0.0))
        res["VISCOSITY_CP"] = (vmin - 1e-6) <= visc <= (vmax + 1e-6)
    else:
        res["VISCOSITY_CP"] = True
        
    # PH [min, max]
    ph_spec = specs.get("PH")
    if ph_spec is not None:
        pmin, pmax = ph_spec
        ph = float(outputs.get("PH", 0.0))
        res["PH"] = (pmin - 1e-6) <= ph <= (pmax + 1e-6)
    else:
        res["PH"] = True
        
    # D50_UM_MAX
    d50_max = specs.get("D50_UM_MAX")
    if d50_max is not None:
        d50 = float(outputs.get("D50_UM", 0.0))
        res["D50_UM_MAX"] = d50 <= (float(d50_max) + 1e-6)
    else:
        res["D50_UM_MAX"] = True
        
    # STABLE
    stable_spec = specs.get("STABLE")
    if stable_spec is not None:
        st = bool(outputs.get("STABLE", False))
        res["STABLE"] = (st == bool(stable_spec))
    else:
        res["STABLE"] = True
        
    # COST_IDR_PER_KG_MAX
    cost_max = specs.get("COST_IDR_PER_KG_MAX")
    if cost_max is not None:
        cost = float(outputs.get("COST_IDR_PER_KG", cost_idr_per_kg(formula)))
        res["COST_IDR_PER_KG_MAX"] = cost <= (float(cost_max) + 1e-6)
    else:
        res["COST_IDR_PER_KG_MAX"] = True
        
    res["ALL"] = all(res.values())
    return res


def sample_valid(
    n: int,
    rng: Optional[np.random.RandomState] = None,
    bounds_override: Optional[Dict[str, Tuple[float, float]]] = None
) -> pd.DataFrame:
    """
    Uniform random sampling of valid formulas rejecting AQUA < 50.
    Returns DataFrame with columns INGREDIENTS + PROCESS + AQUA + OIL_PHASE.
    """
    if rng is None:
        rng = np.random.RandomState(42)
    b_dict = bounds()
    if bounds_override:
        b_dict.update(bounds_override)
        
    samples = []
    while len(samples) < n:
        batch_size = max((n - len(samples)) * 3, 100)
        cand = {}
        for k in INGREDIENTS:
            lo, hi = b_dict[k]
            cand[k] = rng.uniform(lo, hi, size=batch_size)
            
        # Process
        for p in PROCESS:
            lo, hi = b_dict[p]
            cand[p] = rng.uniform(lo, hi, size=batch_size)
            
        df_batch = pd.DataFrame(cand)
        non_aqua = df_batch[INGREDIENTS].sum(axis=1)
        df_batch["AQUA"] = 100.0 - non_aqua
        
        # Valid filter: AQUA >= 50
        valid_df = df_batch[df_batch["AQUA"] >= 50.0].copy()
        if len(valid_df) > 0:
            valid_df["OIL_PHASE"] = (
                valid_df["CCT"] + valid_df["DIMETHICONE"] + 0.5 * valid_df["CETEARYL_ALCOHOL"]
            )
            samples.append(valid_df)
            
    df_res = pd.concat(samples, ignore_index=True).iloc[:n]
    return df_res
