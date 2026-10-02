# Held-out calibration test (truth-based, no atmospheric assumption), 2026-10-02

Principle: a calibration measurement that is withheld from the interpolation is the truth at its own time. For a withheld
zero-air block the true NO2 is 0; for a withheld He/ZA pair the true (1-R)/d is the measured one. Predict it from the kept
calibrations (PCHIP in time, thinning m = keep every m-th calibration), propagate to NO2, and compare. Brackets that contain
a data gap > 3 h (maintenance) are skipped. The withheld measurement carries its own noise, so these numbers are conservative.
Knot noise of the I0 blocks is measured independently from contiguous half blocks: (half_a - half_b)/2.

## Yeosu 2026, reflectivity chain (campaign, 1261 hourly He/ZA knots; relative NO2 error = window mean of d ln((1-R)/d + a_ZA))
Robust SD of the held-out error, % of NO2, by bracket (m hours):
| m (h) | 2 | 3 | 4 | 6 | 8 | 12 |
|---|---|---|---|---|---|---|
| 300 C | 1.20 | 1.29 | 1.34 | 1.50 | 1.66 | 1.90 |
| 180 C | 0.77 | 0.90 | 0.87 | 0.95 | 1.02 | 1.11 |
Inter-channel correlation of the held-out error at m = 2: 0.49 (shared calibration-gas line).

## Yeosu 2026, zero-air (I0) chain (budget window 05-18..24, 157 ZA blocks; NO2 in ppb through the operational fit, shift fixed
at the median ambient value: 300 C -5.96 px, 180 C -0.56 px)
| channel | quantity | m | n | robust (ppb) | SD (ppb) |
|---|---|---|---|---|---|
| 300 C | held-out error | 2 | 155 | 0.0539 | 0.0614 |
| 300 C | held-out error | 3 | 308 | 0.0598 | 0.0676 |
| 300 C | held-out error | 4 | 459 | 0.0610 | 0.0694 |
| 300 C | held-out error | 6 | 755 | 0.0617 | 0.0730 |
| 300 C | knot noise (half-block) | 0 | 157 | 0.0247 | 0.0257 |
| 180 C | held-out error | 2 | 155 | 0.0541 | 0.0577 |
| 180 C | held-out error | 3 | 308 | 0.0632 | 0.0665 |
| 180 C | held-out error | 4 | 459 | 0.0692 | 0.0782 |
| 180 C | held-out error | 6 | 755 | 0.0779 | 0.0949 |
| 180 C | knot noise (half-block) | 0 | 157 | 0.0389 | 0.0400 |

Sigma ANs combination (paired knots; I0 errors of the two channels correlate only 0.07-0.10):

| quantity | m | g | robust (ppb) | SD (ppb) |
|---|---|---|---|---|
| knot_noise | 0 | 0.9524 | 0.0440 | 0.0444 |
| knot_noise | 0 | 1.21 | 0.0547 | 0.0532 |
| heldout | 2 | 0.9524 | 0.0667 | 0.0780 |
| heldout | 2 | 1.21 | 0.0828 | 0.0881 |
| heldout | 3 | 0.9524 | 0.0804 | 0.0926 |
| heldout | 3 | 1.21 | 0.0971 | 0.1055 |
| heldout | 6 | 0.9524 | 0.0972 | 0.1350 |
| heldout | 6 | 1.21 | 0.1131 | 0.1567 |

### Realised error at the operational 1-h cadence (Sigma ANs, g' = 0.9524), decomposition
- knot-noise part: per knot 0.044 ppb; propagated to a record through interpolation, sqrt(2/3) x 0.044 = 0.036 ppb.
- drift part at a 2-h bracket: sqrt(0.0667^2 - 1.5 x 0.044^2) = 0.039 ppb; at 1 h it is smaller by an unknown factor.
- reflectivity part: ~0.014 ppb. Derived from the Yeosu R held-out test at m = 2 (robust 1.20 % / 0.77 %): knot noise s = robust/sqrt(1.5) = 0.98 % / 0.63 %, propagated to a record at 1-h cadence as sqrt(2/3)*s = 0.80 % (300 C) / 0.51 % (180 C) of channel NO2 (2.03 / 1.63 ppb), combined with g' = 0.9524 and inter-channel correlation 0.49.
=> realised calibration-chain term ~0.036-0.055 ppb = 0.66-1.0 x the 60-s fit sigma of Sigma ANs (0.0546 ppb).
The leave-one-out budget gave 0.070 ppb (1.28 sigma, robust): LOO overestimates by ~1.3-1.9.
This term does not average down within an interval: an hourly mean keeps ~0.031-0.05 ppb while the fit error of the mean is ~0.007 ppb.

### Closure with the observed record (2-h high-pass of 5-min means, g = 1.21)
simulated knot noise 0.019 + fit noise 0.029 -> 0.036 ppb (robust) versus observed 0.0435 ppb; remainder ~0.025 ppb for drift +
atmosphere. CORRECTION: the 2-h high-pass removes ~60 % of a knot-noise (hourly piecewise-linear) error, so the earlier statement
'realised error <= 0.6-0.7 fit sigma' (consistency_reconcile_2026-10-02) applied a filtered bound to an unfiltered quantity and is withdrawn.

## Seosan 2020 (raw-derived, 11 knot pairs, brackets 7.5-20.7 h; knots 5-6 bracket the maintenance stop and are excluded)
- reflectivity chain held-out error: RMS 0.52 % (ch1) / 0.77 % (ch2) of NO2.
- I0 chain held-out NO2 error: RMS 0.137 ppb (ch1) / 0.037 ppb (ch2) (~1.5 % / 0.4 % of NO2). No half blocks -> includes held-out noise.
CORRECTION: the earlier 'slow error ~4 % of NO2' (from LOO and the ch1-ch2 scatter) is not supported by the truth-based test.

## Reading
1. The calibration-chain term is set mainly by the noise of each calibration measurement, not by the interval length:
   Yeosu I0 error grows only from 0.054 to 0.062 (300 C) and 0.054 to 0.078 ppb (180 C) between 2- and 6-h brackets, and the
   Seosan reflectivity error at 8-20 h brackets is not larger in % than Yeosu's at 2 h. (Agrees with the 2026-09-20 README of
   i0_interp_2026-09: 'not interpolation but measurement noise'.)
2. Its size is comparable to the 60-s fit error, it is invisible to the fit statistics, and it does not average down within an interval,
   so it dominates averaged products (hourly means by ~4-7x).
Caveats: one week at Yeosu for I0; half-block noise from contiguous halves; drift share at 1 h not resolved; Seosan without knot noise.
