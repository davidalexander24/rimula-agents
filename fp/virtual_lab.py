"""FormulaPilot Virtual Lab Skincare Simulator (§8.1.2, §8.1.3, §8.1.4)"""
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple
from fp.palette import INGREDIENTS, PROCESS, complete, cost_idr_per_kg

OUTPUTS = [
    "VISCOSITY_CP",
    "PH",
    "D50_UM",
    "STABILITY_INDEX",
    "STABLE",
    "COST_IDR_PER_KG",
]

DEFAULT_VARIANTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "virtual_lab",
    "variants.json",
)


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0))))


def _build_default_variants() -> Dict[str, Any]:
    """
    Generate variants definitions (§8.1.3):
    v1: calibrated equations
    v2: coefficients multiplied by random U(0.75, 1.25) with seed 2
    v3: v1 + extra interactions & higher noise
    """
    v1 = {
        "variant": "v1",
        "description": "Base calibrated equations",
        "ph": {
            "base": 5.2,
            "nia_coef": 0.08,
            "car_coef": -2.0,
            "naoh_excess_coef": 1.2,
            "noise_sigma": 0.10,
            "clip": [3.0, 9.0],
        },
        "viscosity": {
            "log10_base": 2.0,
            "xan_coef": 1.2,
            "car_coef": 3.5,
            "car_sig_mult": 3.0,
            "car_sig_shift": 4.5,
            "cet_coef": 0.18,
            "oil_coef": 0.02,
            "gly_coef": 0.01,
            "noise_sigma": 0.05,
        },
        "d50": {
            "base": 0.8,
            "oil_mult": 25.0,
            "rpm_ref": 4000.0,
            "rpm_exp": 0.7,
            "hmin_ref": 3.0,
            "hmin_exp": 0.3,
            "emul_denom_base": 0.5,
            "emul_denom_mult": 4.0,
            "temp_ref": 75.0,
            "temp_coef": 0.01,
            "noise_sigma": 0.10,
        },
        "stability": {
            "sig_intercept": -4.0,
            "emul_ratio_mult": 2.5,
            "emul_ratio_max": 1.5,
            "log_visc_mult": 0.8,
            "ln_d50_mult": -0.6,
            "nia_ph_mult": -0.25,
            "low_ph_pen": -1.5,
            "high_oil_pen": -1.0,
            "flip_prob": 0.05,
        },
    }

    # Generate v2 by scaling numeric coefficients by U(0.75, 1.25) with seed 2
    rng2 = np.random.RandomState(2)

    def scale_dict(d):
        res = {}
        for k, val in d.items():
            if isinstance(val, dict):
                res[k] = scale_dict(val)
            elif (
                isinstance(val, (int, float))
                and not k.startswith("clip")
                and k not in ("flip_prob", "temp_ref", "rpm_ref", "hmin_ref")
            ):
                scale = rng2.uniform(0.75, 1.25)
                res[k] = round(float(val * scale), 5)
            else:
                res[k] = val
        return res

    v2 = scale_dict(v1)
    v2["variant"] = "v2"
    v2["description"] = "Robustness variant with randomly scaled coefficients"

    # v3 has new interactions and 1.5x noise (§8.1.3)
    v3 = json.loads(json.dumps(v1))
    v3["variant"] = "v3"
    v3["description"] = "Extra interactions and higher noise"
    v3["ph"]["noise_sigma"] = 0.15
    v3["viscosity"]["noise_sigma"] = 0.075
    v3["d50"]["noise_sigma"] = 0.15
    v3["stability"]["flip_prob"] = 0.075
    v3["extra_interactions"] = {
        "gly_stability_pen": -0.4,
        "dimethicone_d50_mult": 0.03,
    }

    return {"v1": v1, "v2": v2, "v3": v3}


class VirtualLab:
    """
    Virtual Lab skincare simulator (§8.1.2, §8.1.3).
    """

    def __init__(
        self,
        variant: str = "v1",
        seed: Optional[int] = None,
        variants_path: Optional[str] = None,
    ):
        self.variant = variant
        self.seed = seed
        self.rng = np.random.RandomState(seed) if seed is not None else np.random.RandomState()
        
        if variants_path and os.path.exists(variants_path):
            with open(variants_path, "r", encoding="utf-8") as f:
                all_v = json.load(f)
        else:
            all_v = _build_default_variants()
            
        if variant not in all_v:
            raise ValueError(f"Unknown variant '{variant}'. Available: {list(all_v.keys())}")
        self.params = all_v[variant]

    def _compute(self, formula: Dict[str, Any], with_noise: bool, rng: np.random.RandomState) -> Dict[str, Any]:
        f = complete(formula)
        
        gly = float(f.get("GLYCERIN", 0.0))
        nia = float(f.get("NIACINAMIDE", 0.0))
        cet = float(f.get("CETEARYL_ALCOHOL", 0.0))
        emu = float(f.get("EMULSIFIER", 0.0))
        cct = float(f.get("CCT", 0.0))
        dim = float(f.get("DIMETHICONE", 0.0))
        xan = float(f.get("XANTHAN", 0.0))
        car = float(f.get("CARBOMER", 0.0))
        naoh = float(f.get("NAOH", 0.0))
        
        rpm = float(f.get("RPM", 4000.0))
        hmin = float(f.get("HMIN", 3.0))
        temp = float(f.get("TEMP", 75.0))
        
        # Intermediates
        oil = cct + dim + 0.5 * cet
        emul_active = emu + 0.3 * cet
        neut = min(naoh / (1.5 * car + 1e-6), 1.2)
        
        # 1. pH calculation
        p_ph = self.params["ph"]
        ph_noise = rng.normal(0.0, p_ph["noise_sigma"]) if with_noise else 0.0
        ph_raw = (
            p_ph["base"]
            + p_ph["nia_coef"] * nia
            + p_ph["car_coef"] * car * (1.0 - min(neut, 1.0))
            + p_ph["naoh_excess_coef"] * max(naoh - 1.5 * car, 0.0)
            + ph_noise
        )
        ph_val = float(np.clip(ph_raw, p_ph["clip"][0], p_ph["clip"][1]))
        
        # 2. Viscosity calculation
        p_visc = self.params["viscosity"]
        visc_noise = rng.normal(0.0, p_visc["noise_sigma"]) if with_noise else 0.0
        car_term = (
            p_visc["car_coef"]
            * car
            * min(neut, 1.0)
            * _sigmoid(p_visc["car_sig_mult"] * (ph_val - p_visc["car_sig_shift"]))
        )
        log10_visc = (
            p_visc["log10_base"]
            + p_visc["xan_coef"] * xan
            + car_term
            + p_visc["cet_coef"] * cet
            + p_visc["oil_coef"] * oil
            + p_visc["gly_coef"] * gly
            + visc_noise
        )
        viscosity_cp = float(10.0 ** log10_visc)
        
        # 3. Droplet size D50 calculation
        p_d50 = self.params["d50"]
        d50_noise = rng.normal(0.0, p_d50["noise_sigma"]) if with_noise else 0.0
        
        denom = p_d50["emul_denom_base"] + p_d50["emul_denom_mult"] * emul_active / max(oil, 1.0)
        rpm_factor = (p_d50["rpm_ref"] / max(rpm, 100.0)) ** p_d50["rpm_exp"]
        hmin_factor = (p_d50["hmin_ref"] / max(hmin, 0.1)) ** p_d50["hmin_exp"]
        temp_factor = 1.0 + p_d50["temp_coef"] * abs(temp - p_d50["temp_ref"])
        
        d50_core = p_d50["base"] + p_d50["oil_mult"] * (oil / 100.0) * rpm_factor * hmin_factor / denom
        d50_val = float(d50_core * temp_factor * np.exp(d50_noise))
        
        # v3 extra interaction on d50
        if self.variant == "v3":
            d50_val = d50_val * (1.0 - 0.03 * dim)
            
        d50_val = max(d50_val, 0.1)
        
        # 4. Stability index
        p_stab = self.params["stability"]
        emul_ratio = min(emul_active / max(0.25 * oil, 0.5), p_stab["emul_ratio_max"])
        
        stab_logit = (
            p_stab["sig_intercept"]
            + p_stab["emul_ratio_mult"] * emul_ratio
            + p_stab["log_visc_mult"] * log10_visc
            + p_stab["ln_d50_mult"] * np.log(d50_val)
            + (p_stab["nia_ph_mult"] * max(nia - 5.0, 0.0) if ph_val < 5.5 else 0.0)
            + (p_stab["low_ph_pen"] if ph_val < 4.5 else 0.0)
            + (p_stab["high_oil_pen"] if (oil > 15.0 and emul_active < 3.0) else 0.0)
        )
        
        if self.variant == "v3":
            if gly > 7.0:
                stab_logit += -0.4
                
        stability_index = _sigmoid(stab_logit)
        
        # Stable binary
        is_stable = bool(stability_index > 0.5)
        if with_noise:
            if rng.uniform(0.0, 1.0) < p_stab["flip_prob"]:
                is_stable = not is_stable
                
        # 5. Cost
        cost_val = cost_idr_per_kg(f)
        
        return {
            "VISCOSITY_CP": round(viscosity_cp, 2),
            "PH": round(ph_val, 3),
            "D50_UM": round(d50_val, 3),
            "STABILITY_INDEX": round(stability_index, 4),
            "STABLE": is_stable,
            "COST_IDR_PER_KG": cost_val,
        }

    def run_batch(self, formula: Dict[str, Any], seed_override: Optional[int] = None) -> Dict[str, Any]:
        """Run batch simulation with experimental noise (§8.1.4)."""
        rng = np.random.RandomState(seed_override) if seed_override is not None else self.rng
        res = self._compute(formula, with_noise=True, rng=rng)
        res["variant"] = self.variant
        res["noise_seed"] = seed_override if seed_override is not None else self.seed
        return res

    def true_mean(self, formula: Dict[str, Any]) -> Dict[str, Any]:
        """Compute expected mean values without noise. Strictly for testing & model card."""
        res = self._compute(formula, with_noise=False, rng=np.random.RandomState(0))
        res["variant"] = self.variant
        return res


def save_variants_json(path: Optional[str] = None):
    """Generate and save variants.json."""
    if path is None:
        path = DEFAULT_VARIANTS_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    all_v = _build_default_variants()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_v, f, indent=2)
    return path
