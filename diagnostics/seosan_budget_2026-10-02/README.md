# Seosan 2020 leave-one-knot-out budget (2026-10-02)

Second dataset for the AMT referee point "one incident / one instrument" and for interval-length dependence.
Data: `C:\GHL\old_missions\Seosan2020\raw` (copied from E:\old\Seosan), 2020-11-21..25, CAESAR Blue, two channels
(block1 = cols 5-2052 = ch1, block2 = cols 2053-4100 = ch2). Channel physical identity (cold/heated) **not verified**
for 2020; both retrieve NO2 with medians 9.29 / 9.33 ppb, r = 0.998.

## Calibration knots
* Two regimes. 11-21 to 11-22 ~13 h: short in-file cal blocks (flags 500-503, 510-513) every ~2 files. Flag-to-gas mapping is
  inconsistent between files (He-level intensity appears in the 500 block in one file and only in 503 in another), so these were **not used**.
* From 11-22 evening: dedicated calibration file pairs, 3 per day. He = the brighter file of each pair (+16-21 %).
  Pair 11-21-034/035 (ratio 1.007, different flag set 660-663) dropped. **11 knot pairs**, doy 327.64-330.72; gaps 2.7-16.5 h.
* (1-R)/d = (I_ZA a_ZA - I_He a_He)/(I_He - I_ZA), Augur Rayleigh at nominal 20 C, 1013.25 hPa (no measured T/P).
  L_eff = d/(1-R): ch1 7.1 km, stepping to 8.7-8.9 km between knots 5 and 6 (doy 329.41 -> 329.54); ch2 10.2-11.2 km.
  Old pipeline Rs path length ~6.5 km (ch1) - consistent within the T/P/Rayleigh-formula difference.

## Fit
Provisional fitsets (`seosan_operational_2026-09/stage2_input`), refs from `DOASIS_Blue/ref_blue` (SHA-256 verified),
window 440.03-454.98 nm, poly 3. ILS FWHM 14 px chosen by minimum residual (scan 4-18 px; NO2 changes ~+2 %/px of FWHM -
a systematic that does not enter the LOO differences). Free shift 5.4-6.5 px (ch1), 6.4-7.6 px (ch2) against the provisional Hg wavecal,
then **fixed** at 5.65 / 6.71 px. Squeeze is unconstrained by the data (0.985-1.0) and left at 1.
4101 ambient 60-s bins inside the knot range; 3939 have a LOO value (end-knot neighbourhoods excluded, no extrapolation).

## Result (tri = nearest ZA and He pair both removed; units of each record's own fit sigma)

| dataset | group | n | median abs(d)/sigma | 95th pct | frac > 1 sigma | median abs(d) % NO2 |
|---|---|---|---|---|---|---|
| Yeosu 300 °C | all, ~2 h | 8847 | 1.21 | 6.9 | 0.57 | 2.1 |
| Yeosu 180 °C | all, ~2 h | 8847 | 0.74 | 2.6 | 0.38 | 2.0 |
| Seosan ch1 | all | 3939 | 2.27 | 16.9 | 0.71 | 2.2 |
| Seosan ch1 | 7.5–7.8 h | 553 | 2.04 | 5.3 | 0.80 | 4.4 |
| Seosan ch1 | 18–21 h | 3386 | 2.32 | 17.4 | 0.69 | 2.0 |
| Seosan ch1 | 18–21 h, excl. R-step knot | 2900 | 2.00 | 4.8 | 0.64 | 2.0 |
| Seosan ch2 | all | 3939 | 1.17 | 45.9 | 0.54 | 1.0 |
| Seosan ch2 | 7.5–7.8 h | 553 | 0.51 | 16.9 | 0.30 | 1.0 |
| Seosan ch2 | 18–21 h | 3386 | 1.40 | 47.6 | 0.58 | 0.9 |
| Seosan ch2 | 18–21 h, excl. R-step knot | 2900 | 1.02 | 2.4 | 0.51 | 0.9 |

Yeosu rows: production_budget_clockfixed.csv (a_tri/b_tri) with per-record Augur sigma from residual_corr_2026-09-30/field_*.csv,
non-bound records of the budget window (n = 8847). Yeosu LOO brackets are ~2 h; Seosan brackets are 7.5-7.8 h or 18-21 h.

Reading:
1. Typical records: median abs(d)/sigma is 1-2.3 in both datasets; in % of NO2 it is ~1-2 % in both. Interval length alone
   (7.5 vs 18-21 h) changes the typical value little (ch1 2.04 vs 2.32).
2. The tail is set by one discrete event, the R step between knots 5 and 6. Removing knot 5 forces interpolation across the step:
   ch1 -1.4 ppb, ch2 +3.4 ppb (15-35 % of NO2, up to ~40 sigma). Excluding that knot, the 18-21 h 95th percentile drops from
   17 to 4.8 (ch1) and from 48 to 2.4 (ch2). Knot 6 (short group) also brackets the step and carries the ch2 short-group tail.
3. Fit report: Spearman(abs d, rms) = 0.66 / 0.53, but Spearman(abs d, NO2) = 0.65 / 0.47 and Spearman(abs d, rms/sigma) = 0.10 / -0.49;
   both scale with NO2. LOO raises rms by a median 8 / 12 % (20 / 34 % for the top 5 % of abs d): visible in a perturbation
   experiment, not usable as a per-record flag without a reference fit. Same qualitative result as Yeosu.
4. Base-product consequence: in the 3-h interval containing the R step (doy 329.41-329.54) the production interpolation is itself
   wrong by an unknown fraction of the step. ch1/ch2 ratio drifts from ~1.00 near knots to +4.6 % at 5-8.5 h from a knot in long
   intervals (n = 763) - suggestive only, because channel identity (possible PN signal in one channel) is unverified.

Caveats: nominal T/P; no in-file cal blocks; LOO doubles the bracket and overestimates the true interpolation error
(Yeosu simulation: x1.16-1.26); provisional wavecal and FWHM.

Files: stage1_bins_knots.py, stage2_loo.py (functions as run), seosan_loo_results.npz, results.json,
loo_compare_yeosu_seosan.csv (all terms i0/rt/tri), seosan_loo_by_knot.csv, seosan_loo_budget.png.
