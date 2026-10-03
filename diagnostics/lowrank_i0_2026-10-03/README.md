# A1 decision test: low-rank I0 model (2026-10-03)

Question: does a low-rank I0 model (ln I0 in the fit window +-3 nm = mean shape + k principal modes + Chebyshev deg 3, basis from other ZA blocks)
reduce the ppb-level I0 knot noise and held-out error of the operational NO2 fit? Data: Yeosu 05-18..24, 157 ZA blocks per hot channel,
operational fit settings, shift fixed (ch1 -5.96 px, ch2 -0.56 px), as in diagnostics/heldout_calib_2026-10-02. sumANs = ch1 - 0.9524 ch2.
Script: lowrank_i0_test.py (run through diagnostics/runtime_2026-09-30/qtstub_run.py). Rows: lowrank_i0_rows.csv.

## Knot test (half-split: reconstruct half A, compare with independent half B, subtract half-B noise)
Robust SD, ppb. 'current' = noise of the full measured block (as used in operation).
| | ch1 (300 C) | ch2 (180 C) | sumANs |
|---|---|---|---|
| current full-block noise | 0.0247 | 0.0389 | 0.0440 |
| raw half-block noise | 0.0349 | 0.0552 | 0.0625 |
| low-rank k=1, half block | 0.1077 | 0.0604 | 0.1246 |
| low-rank k=2 | 0.0307 | 0.0471 | 0.0774 |
| low-rank k=3 | 0.0280 | 0.0330 | 0.0423 |
| low-rank k=5 | 0.0280 | 0.0252 | 0.0451 |
The low-rank numbers are for a reconstructed HALF block. A reconstructed full block lies between that value and value/sqrt(2)
(the latter only if the remaining error is pure noise); for sumANs k=3 this is 0.030-0.042 ppb vs 0.044 now (4-32 % lower).

## Held-out prediction (withheld ZA block = truth; contains its own noise 0.044 ppb in sumANs)
| m | method | n | ch1 | ch2 | sumANs robust | sumANs prediction error (truth noise removed) |
|---|---|---|---|---|---|---|
| 2 | lowrank3_pchip | 155 | 0.0439 | 0.0565 | 0.0684 | 0.0524 |
| 2 | raw_pchip | 155 | 0.0539 | 0.0541 | 0.0667 | 0.0502 |
| 3 | lowrank3_pchip | 308 | 0.0505 | 0.0584 | 0.0831 | 0.0705 |
| 3 | raw_pchip | 308 | 0.0598 | 0.0632 | 0.0834 | 0.0709 |
| 6 | lowrank3_pchip | 755 | 0.0619 | 0.0700 | 0.1004 | 0.0902 |
| 6 | raw_pchip | 755 | 0.0617 | 0.0779 | 0.1048 | 0.0951 |

## Verdict
The pixel-RMS reduction seen earlier (about 3-4x, idea_A1_lowrank_I0_test.csv) does NOT carry over to NO2/sumANs.
At ppb level the low-rank I0 changes the held-out sumANs error by -4 to +3 % (m = 6 / 2) and the knot term by at most about a third
(bounded, not measured). The pre-agreed criterion (sumANs knot noise from 0.044 to below about 0.02 ppb) is not met. A1 is dropped as a paper thesis.
Not tested: a different mode count per channel, fitting the modes jointly in the ambient fit, campaign-wide data.
Interpretation (not tested): the part of the I0 knot noise that projects onto NO2 is structured within-block variation that the
shared modes do not capture, while the pixel-white part they remove projects weakly onto NO2.
