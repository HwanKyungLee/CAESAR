"""core/structural.py — per-record structural perturbations from an alpha row (manuscript §4.2, §6.1).

The fit uncertainty cannot contain errors in the inputs interpolated to the scan's time — zero
air I₀(t), reflectivity R(t), the fixed etalon frequency f — because they leave the residual
unchanged. A structural term is measured by perturbing an input the way the pipeline can actually
be wrong and re-fitting:

    i0   remove the nearest zero-air knot, re-interpolate I₀
    rt   remove the R knot nearest that zero-air knot, re-interpolate (1−R)/d
    ef   fit with the scan's own detected f instead of the fixed one (done at fit time)
    tri  all three at once

The perturbed alpha is rebuilt from the alpha row itself. Alpha generation saves the knots it
used (`{campaign}/_zeroair/calib_knots_*.npz`: ZA spectra, T/P, step breaks, and R(t) already on
the alpha's pixel axis), and the BBCEAS equation inverts exactly:

    α = (ω + RL·α_ZA)·q − (α_s − α_ZA),   q = I₀/I − 1   ⇒   I/I₀ = 1/(1+q)
    α' = (ω' + RL·α_ZA)·[(I₀'/I₀)(1+q) − 1] − (α_s − α_ZA)

so no raw is re-read and the assembly cannot drift from production. As in the canonical run
(diagnostics/i0_interp_2026-09/production_budget.py), α_ZA uses the full-knot T/P, and records whose
nearest zero-air knot is the first or last one are skipped (LOO there is extrapolation).

Self-check: python -m core.structural
"""
from __future__ import annotations

import numpy as np

from core.step_guard import SegmentedPchip

R_PAIR_MAX_S = 3600.0     # an R knot farther than this from the zero-air knot is not "its" R knot


class CalibKnots:
    """The I₀ and R knots of one alpha-generation run (calib_knots_*.npz)."""

    def __init__(self, path_or_dict):
        d = dict(np.load(path_or_dict, allow_pickle=False)) if isinstance(path_or_dict, str) else path_or_dict
        self.za_x = np.asarray(d["za_x"], float)
        self.za_arr = np.asarray(d["za_arr"], float)
        self.za_t = np.asarray(d["za_t"], float)
        self.za_p = np.asarray(d["za_p"], float)
        self.i0_breaks = list(np.asarray(d.get("i0_breaks", []), float))
        self.za_ref = np.asarray(d["za_ref"], float)
        self.rl = float(d["rl_factor"])
        self.r_sec = np.asarray(d.get("r_sec", np.zeros(0)), float)
        self.r_omr = np.asarray(d.get("r_omr", np.zeros((0, 0))), float)
        self.r_breaks = list(np.asarray(d.get("r_breaks", []), float))
        self._pi0 = SegmentedPchip(self.za_x, self.za_arr, break_x=self.i0_breaks)
        self._pt = SegmentedPchip(self.za_x, self.za_t, break_x=self.i0_breaks)
        self._pp = SegmentedPchip(self.za_x, self.za_p, break_x=self.i0_breaks)
        self._por = (SegmentedPchip(self.r_sec, self.r_omr, break_x=self.r_breaks)
                     if len(self.r_sec) >= 2 else None)
        self._loo_cache: dict = {}

    def _i0_loo(self, k):
        if ("i0", k) not in self._loo_cache:
            keep = np.ones(len(self.za_x), bool)
            keep[k] = False
            self._loo_cache[("i0", k)] = SegmentedPchip(self.za_x[keep], self.za_arr[keep],
                                                        break_x=self.i0_breaks)
        return self._loo_cache[("i0", k)]

    def _r_loo(self, kr):
        if ("r", kr) not in self._loo_cache:
            keep = np.ones(len(self.r_sec), bool)
            keep[kr] = False
            self._loo_cache[("r", kr)] = SegmentedPchip(self.r_sec[keep], self.r_omr[keep],
                                                        break_x=self.r_breaks)
        return self._loo_cache[("r", kr)]

    def nearest_za(self, sec):
        return int(np.argmin(np.abs(self.za_x - float(sec))))

    def r_knot_for(self, k):
        """Index of the R knot paired with zero-air knot k, or None (none within R_PAIR_MAX_S, or an
        edge knot whose removal would be extrapolation)."""
        if self._por is None:
            return None
        kr = int(np.argmin(np.abs(self.r_sec - self.za_x[k])))
        if not (0 < kr < len(self.r_sec) - 1) or abs(self.r_sec[kr] - self.za_x[k]) > R_PAIR_MAX_S:
            return None
        return kr

    def perturbed(self, alpha, sec, T_s, P_s):
        """{'base','i0','rt','tri'} alphas for one record (rt/tri None without a paired R knot),
        plus 'k' and 'kr'. None when the record's nearest zero-air knot is an edge knot."""
        if self._por is None:          # no R(t) knots: ω(t) unknown, the alpha cannot be inverted
            return None
        k = self.nearest_za(sec)
        if k <= 0 or k >= len(self.za_x) - 1:
            return None
        alpha = np.asarray(alpha, float)
        T0, P0 = float(self._pt(sec)), float(self._pp(sec))
        a_ref = self.za_ref * (P0 / 1013.25) * (273.15 / (T0 + 273.15))
        a_s = self.za_ref * (float(P_s) / 1013.25) * (273.15 / (float(T_s) + 273.15))
        om_f = np.asarray(self._por(sec), float)
        i0_f = np.asarray(self._pi0(sec), float)
        with np.errstate(divide="ignore", invalid="ignore"):
            q = (alpha + a_s - a_ref) / (om_f + self.rl * a_ref)
            i0_l = self._i0_loo(k)(sec)
            ratio_i0 = (np.asarray(i0_l, float) / i0_f) if i0_l is not None else None

        def assemble(om, i0_ratio):
            qq = q if i0_ratio is None else i0_ratio * (1.0 + q) - 1.0
            return (om + self.rl * a_ref) * qq - (a_s - a_ref)

        kr = self.r_knot_for(k)
        om_l = np.asarray(self._r_loo(kr)(sec), float) if kr is not None else None
        out = {"k": k, "kr": kr, "base": alpha,
               "i0": assemble(om_f, ratio_i0) if ratio_i0 is not None else None,
               "rt": assemble(om_l, None) if om_l is not None else None}
        out["tri"] = (assemble(om_l, ratio_i0) if (om_l is not None and ratio_i0 is not None) else None)
        return out


if __name__ == "__main__":
    nk, npx = 7, 20
    x = np.arange(nk) * 3600.0
    rng = np.random.default_rng(0)
    za = 30000.0 * (1 + 0.01 * rng.normal(size=(nk, npx)))
    K = CalibKnots(dict(za_x=x, za_arr=za, za_t=np.full(nk, 25.0), za_p=np.full(nk, 1000.0),
                        za_ref=np.full(npx, 1e-8), rl_factor=1.0, r_sec=x + 60,
                        r_omr=np.full((nk, npx), 2e-6) * (1 + 0.01 * rng.normal(size=(nk, npx)))))
    from core.physics import bbceas_alpha
    sec, I = 2.4 * 3600, 29000.0 * np.ones(npx)
    a_ref = K.za_ref * (1000.0 / 1013.25) * (273.15 / 298.15)
    alpha = bbceas_alpha(I, K._pi0(sec), K._por(sec), a_ref, a_ref, 1.0)
    p = K.perturbed(alpha, sec, 25.0, 1000.0)
    want = bbceas_alpha(I, K._i0_loo(p["k"])(sec), K._por(sec), a_ref, a_ref, 1.0)
    assert np.allclose(p["i0"], want, rtol=1e-10), "i0 perturbation must equal re-assembly from I"
    want = bbceas_alpha(I, K._pi0(sec), K._r_loo(p["kr"])(sec), a_ref, a_ref, 1.0)
    assert np.allclose(p["rt"], want, rtol=1e-10), "rt perturbation must equal re-assembly from I"
    print("structural: OK (inversion == re-assembly from I)")
