# CHANGES 2026-10-03 — §6 intro: implementation status of the §6.1 convention

Baseline: state after the 2026-09-30 round. Full diff: `CHANGES_2026-10-03_edit.diff`. One paragraph, no number changed.

## 1. Item
- **§6 intro** — "The reporting convention of Sect. 6.1 is implemented in part: the termination state, the distance to the
  nearest knot and the identity of the reference file are exported, while the build time and time convention … are specified
  for implementation" → all three numbers implemented:
  - fit uncertainty exported with its residual-correlation (sandwich) counterpart (Sect. 3.4) — Augur `c4c4749`
    (`<gas>_ErrorCorr`, `Resid_ACF1`);
  - structural term computed per record in post-processing under the Sect. 4.2 perturbations, rebuilt from the exported
    record and the stored calibration knots — `f0ff1ed` (`tools/structural_budget.py`, `core/structural.py`; alpha generation
    stores `_zeroair/calib_knots_*.npz`);
  - context flag: termination state, distance to the nearest zero-air and reflectivity knot, bracketing interval, in-range
    flag, reference identity — `f155d2e` (`I0_/R_dt_s`, `_gap_h`, `_edge`);
  - still not exported (stated as "the remaining fields of Table~\ref{tab:context_fields}"): side of the nearest knot, number of adjacent blocks
    rejected by the gates, build time and time convention of each reference.
- **Version wording** — "All three numbers … are implemented" → "In the current version of Augur, later than the v0.2.0 used
  for the results here, all three numbers … are implemented" (`availability.tex` names v0.2.0; the features are later).
- **Claim "on one day of the budget window this reproduces the zero-air and reflectivity terms record by record"** — evidence:
  2026-05-20 hot, alphas regenerated with the new code and the clock-fixed R, 830 records time-matched to
  `diagnostics/i0_interp_2026-09/production_budget_clockfixed.csv`: per-record correlation ANs i0 +0.996, rt +0.998;
  PNs i0 +0.967, rt +0.996 (tri +0.997 / +0.882, ef +0.77 / +0.74 — not claimed). Robust SD ANs i0 0.0540 vs 0.0547,
  rt 0.0452 vs 0.0452; PNs i0 0.0277 vs 0.0348, rt 0.0109 vs 0.0120 ppb. Commit message of `f0ff1ed`.
- Unchanged and still true: §7.3 "the provenance fields among them are specified but not yet implemented"; §8 "Every
  implementation already computes the flag's fields, except the build time and time convention of a reference".

## 2. Word count
sec6_reporting.tex +81 (internal counter; +66 for the paragraph, +15 for the version clause). Main text ≈ 12,701 (was 12,620).

## 3. Not done here
- PDF not rebuilt: no TeX on the editing PC (TinyTeX build per README §2). Rebuild before the next circulation.
- `availability.tex` left at v0.2.0 (the version the results were made with); §6 now says the convention is in a later version.
  When a release containing it is cut, name it there.
