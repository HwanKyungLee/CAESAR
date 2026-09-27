# DOAS extinction-domain retrieval benchmark, v2

261 synthetic extinction spectra with known truth, for testing DOAS-style
retrieval codes. Every spectrum comes from an explicit forward model; no retrieval
code was used to make them, so the benchmark does not favour any implementation.

It does not only ask whether a code gets the right answer. Three of its five groups
ask whether the **uncertainty the code reports** is right, and whether the answer
survives a change of fitting window.

## Two windows

| channel | window | pixels | polynomial |
|---|---|---|---|
| `hot_PNs` | 444.146-470.685 nm | 552 | 3 |
| `cold` | 438.42-475.741 nm | 775 | 4 |

They use different wavelength calibrations and differently convolved cross
sections, as two channels of one instrument do.

## Contents

```
manifest.json                          conventions, units, seed, per-channel windows
reference/cross_sections_<channel>.csv pixel, wavelength_nm, sigma_NO2, sigma_CHOCHO, sigma_H2O
cases/manifest.csv                     one row per case: truth and the fit configuration
cases/spectra.npz                      one array per case_id; grids as pixel__<channel>
generate.py  baseline.py  score.py     regenerate, reference implementation, scorer
example_submission.csv                 output of the reference implementation
example_scorecard.csv                  its score
```

## Forward model

```
alpha(p) = sum_g c_g * sigma_g(p')      gases
         + sum_k a_k * T_k(x(p))        Chebyshev baseline, x in [-1, 1]
         + A * sin(2*pi*f*p + phi)      etalon, where present
         + eps(p)                       noise, where present

p' = centre + (p - centre) * squeeze + shift_px
```

`sigma_g(p')` is linear interpolation of the tabulated cross section onto `p'`.
Units: `alpha` cm-1, `sigma` cm2 molec-1, `c_g` molec cm-3. Noise where present is
Gaussian with RMS 6.16e-09 cm-1, the measured single-scan residual
RMS of the instrument these references came from; AR(1) cases use rho = 0.5.

**Given** per case in `cases/manifest.csv`: channel, window, centre pixel, squeeze
factor, polynomial order to fit, gases to fit, etalon frequency to use.
**To be recovered**: the gas coefficients and the wavelength shift, each with an
uncertainty.

Gas amounts were set by the peak extinction each contributes
(`*_peak_alpha_cm1`), so the cases do not depend on how the reference columns
happen to be normalised.

## Groups

| group | n | question |
|---|---|---|
| `A_exact` | 32 | noise-free, **integer shift and unit squeeze**, so no sub-pixel resampling is involved for any implementation. Pure linear algebra. |
| `B_noise` | 180 | 60 replicates of one truth at three noise conditions. Does the reported uncertainty equal the actual scatter? |
| `C_mismatch` | 16 | the fitted model differs from the generating one (extra ILS width, unmodelled etalon frequency, omitted absorber). How large is the bias, and does the reported uncertainty notice? |
| `D_identifiability` | 5 | a high-order baseline absorbs the shift. Does the code report that the shift is unconstrained, or report a value? |
| `F_subpixel` | 12 | non-integer shift with squeeze. The truth uses band-limited (windowed-sinc) sub-pixel resampling, which coincides with neither linear nor cubic interpolation, so the result measures what the interpolator choice costs. Reported, not scored. |
| `E_window` | 16 | the same truth presented in both windows, paired by `pair_id`. Do the two answers agree within their reported uncertainties? |

Group A is a correctness gate and is deliberately interpolator-neutral: the
shifts are integers and the squeeze is exactly one, so the reference lands on
the pixel grid and any implementation is exact. An earlier version used a
squeeze of 1.002 here, which turned the group into a test of *which* sub-pixel
interpolator a code uses rather than whether its algebra is right — a cubic
interpolator scored 2.4e-3 against a linearly-generated truth and appeared to
fail. That question now lives in group F, where the truth is band-limited and
neither interpolator is privileged.

B, C, D, E and F are the substance.

## Submitting

Write a CSV with `case_id, NO2, NO2_sigma, shift_px, shift_sigma`, optionally
`at_grid_edge` or `termination`, then

```python
import pandas as pd, score
print(score.score(pd.read_csv("cases/manifest.csv"),
                  pd.read_csv("my_submission.csv")).to_string(index=False))
```

## Reference implementation

`baseline.py` is a plain profiled shift search with a column-normalised linear
solve and a covariance-based uncertainty. It is not a recommended implementation;
it fixes the format and gives something to beat.

| group | metric | value | target |
|---|---|---|---|
| A_exact | max relative error | 4.72e-13 | < 1e-6 |
| B_noise:noise x1 | scatter / reported sigma | 1.19 | 1.0 +- 0.2 |
| B_noise:noise x2 | scatter / reported sigma | 1.33 | 1.0 +- 0.2 |
| B_noise:AR(1) 0.5 | scatter / reported sigma | 1.57 | 1.0 +- 0.2 |
| C_mismatch | max |bias| in units of the noise RMS | 1.23 | reported sigma is not expected to cover it |
| D_identifiability | cases declared unconstrained | 4/5 | 5/5 |
| F_subpixel | median |error| from sub-pixel model | 0.000678 | report, do not pass/fail |
| E_window | max window-to-window disagreement (truth > 10x noise) | 0.0465 | within the combined reported sigma |

Four things in that table are why the benchmark exists. The reported uncertainty
tracks the scatter when the residual is white and the model is right, and
understates it by half again when the residual is correlated. Model mismatch
produces bias an order of magnitude larger than the reported uncertainty, which
does not grow to meet it. A retrieval returns wavelength shifts spanning 9.3 px
across cases whose truth spans 8 px without saying the data do not determine
them. And the same truth fitted in two windows gives answers that differ by
0.047 where the signal is well above the noise — small, but equal to the
combined reported uncertainty of 0.043 rather than comfortably inside it, so
the window contributes about as much as everything the fit accounts for. Near
the detection limit the disagreement reaches 0.386 on one pair; that figure is
a property of the signal level, not of the window, and is read in the next
paragraph.

One trap is worth naming because the reference implementation fell into it during
development: with a cross-section column of order 1e-19 and Chebyshev columns of
order 1, the design matrix has a condition number near 1e19 and an unnormalised
least-squares solve returns zero for the gas. Normalise the columns.

On interpolation: against the band-limited truth of group F, linear sub-pixel
resampling costs a median 6.8e-4 in the retrieved amount and cubic 4.1e-5, so
cubic is the better choice by a factor of sixteen and both are well below a
typical reported uncertainty. Groups B to E are generated with linear
resampling; their signals are one to three orders of magnitude larger than this,
so the choice does not affect them.

On reading the C and E figures: both are worst-case metrics, and the worst case
is always the weakest signal, so both are easy to misread.

A case that a submission declares unconstrained is not scored in group C. The
submission has behaved correctly there, and penalising the value it happened to
return would reward silence over an honest flag. In the reference run this
removes exactly one case, `C_missing_a2e-09`, whose truth is 0.32 times the
noise RMS: the reference implementation pushes the shift to the edge of its
grid, marks `at_grid_edge`, and returns an infinite uncertainty, and the -423 %
relative bias that follows is a property of the boundary each code happens to
have rather than of its retrieval. Two codes with different search ranges
produce different numbers there and neither number means anything. The
exclusion is guarded: a case declared unconstrained whose truth was detectable
and whose returned value was in fact within 20 % is counted as a false alarm
and reported, so that flagging everything wins nothing.

What remains after that exclusion is the real result, and it is more useful
than the headline it replaces. The three omitted-absorber cases share almost
the same *absolute* bias (-8.5, -7.5, -7.6 x 1e-9 cm-1) across a fifty-fold
range of NO2, because the omitted CHOCHO and water leak a fixed amount into
NO2 regardless of how much NO2 is there. Model mismatch is an additive offset,
not a scale error, and it is the reported uncertainty's failure to grow with it
- a factor 11 shortfall at the worst case - that the group is built to show.

Group E is read the same way. The 0.386 window-to-window disagreement is one
pair at 3.2 times the noise; above ten times the noise the largest disagreement
is 0.047 against a combined reported uncertainty of 0.043. Small, but equal to
the uncertainty rather than inside it, so the choice of window contributes
about as much as everything the fit accounts for. Pairs in which either window
was declared unconstrained are excluded from the scored figure.

## Provenance and citation

instrument-convolved references from a two-channel thermal-dissociation BBCEAS; NO2 after Vandaele et al., CHOCHO after Volkamer et al., H2O from HITRAN. Cite the original cross-section papers, not this package.

Change from v1: the H2O cross section was re-assembled from HITRAN line data. Its peak value in the
fitting windows is 2.5 % higher than in v1; the NO2 and CHOCHO cross sections are unchanged (correlation
1.00000 with v1). Results for H2O are therefore not directly comparable between v1 and v2.

Cross sections are supplied after applying the instrument's power-of-ten
multipliers ({'NO2': 0, 'CHOCHO': 0, 'H2O': -12}), so the tabulated values are
in cm2 molec-1 and need no further scaling.

Regenerate with `python generate.py`; deterministic under seed 20260921.
