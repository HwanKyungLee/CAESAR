# Does the calibration-chain error average down within an interpolation bracket? (2026-10-03)

Claim under test (heldout_calib_2026-10-02 README, derived, not verified): the I0 calibration-chain error does not average down
within an interval, so an hourly mean keeps ~0.031-0.05 ppb of sumANs while the fit error of the hourly mean is ~0.007 ppb.

Direct test, truth-based: in the held-out I0 test at thinning m (keep every m-th ZA block; ZA spacing median 1.00 h, 10-90 % 0.98-1.02 h),
each bracket contains m-1 withheld blocks whose truth is NO2 = 0. Their prediction errors come from the SAME pair of kept knots.
Correlation between them, after removing the withheld blocks' own noise (half-split knot SD: sumANs 0.0446, ch1 0.0257, ch2 0.0400 ppb,
independent between blocks), tells how much averaging inside a bracket helps. Data: Yeosu 05-18..24, 157 ZA blocks, operational fit, shift fixed.
sumANs = ch1 - 0.9524 ch2. 95 % CIs: bootstrap over brackets (2000x).

## sumANs
| m (bracket, h) | brackets | prediction error SD (ppb) | corr. of errors 1 block (~1 h) apart | variance kept by bracket mean | white-noise expectation |
|---|---|---|---|---|---|
| 3 | 154 | 0.079 | 0.62 [0.45, 0.78] | 0.81 [0.73, 0.89] | 0.50 |
| 4 | 152 | 0.098 | 0.78 [0.68, 0.87] | 0.76 [0.69, 0.83] | 0.33 |
| 6 | 149 | 0.119 | 0.83 [0.74, 0.91] | 0.66 [0.55, 0.75] | 0.20 |

Per channel (same columns) are in within_bracket_correlation.csv: errors 1 block apart correlate 0.43-0.58 (300 C) and 0.84-0.93 (180 C).

## Result
- Errors at truth points about 1 h apart inside the same bracket are strongly correlated (sumANs 0.62-0.83). A bracket mean keeps
  66-81 % of the single-point error variance, against 20-50 % if the errors were white. Averaging inside a bracket helps little. CONFIRMED directly.
- Consequence for hourly means at the operational 1-h cadence: taking the 1-h-apart correlation as a LOWER bound for points within one hour
  (assumption: PCHIP-interpolated error varies smoothly inside a bracket), the hourly mean keeps at least sqrt(0.62-0.83) of the record-level term:
  0.036 x sqrt(0.62) = 0.028 to 0.055 x sqrt(0.83) = 0.050 ppb, versus 0.0546/sqrt(60) = 0.007 ppb fit error of the hourly mean (4-7x).
  This agrees with the earlier derived 0.031-0.05 ppb.

## Limits
- One week (05-18..24), one campaign. Campaign-wide test needs the raw data (E:\Yeosu_2026, not currently granted).
- Within-hour correlation is bounded, not measured (no truth points closer than one ZA interval).
- Truth-noise removal assumes the half-split knot SD equals the noise of a withheld block and is independent between blocks.
- Shift fixed at the median ambient value (as in the source test).
